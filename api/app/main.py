"""Local FastAPI service for the frozen, experimental HGB V2 model."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import sys
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from ml.predictor import JobFailurePredictor

from .playbook import EXPLANATION_NOTE, recommended_checks
from .rag_routes import router as rag_router
from .schemas import (
    BatchPredictionResponse, BatchPredictRequest, FEATURE_SCHEMA_VERSION,
    HealthResponse, JobFeatures, JobInput, MAX_BATCH_SIZE, ModelInfoResponse,
    PredictionResponse, PredictRequest,
)

API_VERSION = "0.1.0"
LOGGER = logging.getLogger("dataflow_sentinel.api")
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False


def create_app(
    model_path: str | Path | None = None,
    explanation_background_path: str | Path | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configured_path = model_path or os.environ.get("SENTINEL_MODEL_PATH")
        if not configured_path:
            raise RuntimeError("Set SENTINEL_MODEL_PATH to the saved model directory or bundle file.")
        path = Path(configured_path).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        threads = int(os.environ.get("SENTINEL_MAX_THREADS", "4"))

        configured_background = (
            explanation_background_path
            or os.environ.get("SENTINEL_EXPLANATION_BACKGROUND")
        )

        background_path = None

        if configured_background:
            background_path = Path(
                configured_background
            ).expanduser()

            if not background_path.is_absolute():
                background_path = (
                    PROJECT_ROOT / background_path
                )

        predictor = JobFailurePredictor(
            path,
            max_threads=threads,
            explanation_background_path=background_path,
        )

        # Warm up SHAP once during API startup so the first user
        # prediction does not pay the Numba/JIT compilation cost.
        # Ten rows exercise the multi-row explanation path as well.
        if predictor.explanation_available:
            warmup_frame = pd.read_csv(
                background_path
            ).head(10)

            # Warm the multi-row SHAP path.
            predictor.explain_batch(
                warmup_frame,
                top_k=5,
            )

            # Warm the single-row path separately. SHAP/Numba may
            # compile additional code for a one-row explanation.
            predictor.explain_batch(
                warmup_frame.head(1),
                top_k=5,
            )

        if predictor.feature_columns != list(JobFeatures.model_fields):
            raise RuntimeError("The loaded model does not match the API feature schema.")
        app.state.predictor = predictor
        info = predictor.model_info
        app.state.model_version = f"{info['model_name']}@{info['model_created_at_utc']}"
        try:
            yield
        finally:
            app.state.predictor = None

    app = FastAPI(
        title="DataFlow Sentinel", version=API_VERSION, lifespan=lifespan,
        description=(
            "Local experimental Job-risk scoring. Scores are uncalibrated; "
            "pre-run feature availability is unverified in the source data."
        ),
    )

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        request.state.request_id = uuid4().hex
        started = perf_counter()
        exception_type = None
        try:
            response = await call_next(request)
        except Exception as exc:
            exception_type = type(exc).__name__
            response = JSONResponse(
                status_code=500,
                content={"detail": "Prediction service error.", "request_id": request.state.request_id},
            )
        response.headers["X-Request-ID"] = request.state.request_id
        route = request.scope.get("route")
        event = {
            "event": "api_request",
            "request_id": request.state.request_id,
            "method": request.method,
            "route": getattr(route, "path", "<unmatched>"),
            "model_version": getattr(app.state, "model_version", None),
            "latency_ms": round((perf_counter() - started) * 1000, 3),
            "status_code": response.status_code,
            "validation_outcome": (
                "accepted" if response.status_code < 400
                else "rejected" if response.status_code in (409, 422) else "error"
            ),
        }
        if exception_type:
            event["error_type"] = exception_type
        event.update(getattr(request.state, "score_summary", {}))
        LOGGER.info(json.dumps(event, allow_nan=False))
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Do not echo raw input. Removing input/context also makes NaN/Infinity
        # validation errors JSON-safe instead of accidentally returning 500.
        details = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": details, "request_id": request.state.request_id})

    def get_predictor() -> JobFailurePredictor:
        predictor = getattr(app.state, "predictor", None)
        if predictor is None:
            raise HTTPException(status_code=503, detail="Model is not loaded.")
        return predictor

    def check_version(expected: str | None):
        if expected is not None and expected != app.state.model_version:
            raise HTTPException(status_code=409, detail="Requested model version does not match the loaded model.")

    def score_jobs(jobs: list[JobInput], request: Request) -> list[PredictionResponse]:
        predictor = get_predictor()
        # IDs and request metadata are deliberately outside this matrix.
        frame = pd.DataFrame([job.features.model_dump() for job in jobs])
        try:
            predictions = predictor.predict_batch(frame)

            if predictor.explanation_available:
                explanations = predictor.explain_batch(
                    frame,
                    top_k=5,
                )
            else:
                explanations = [None] * len(jobs)

        except (ValueError, TypeError, OverflowError) as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        scores = predictions["score"]
        request.state.score_summary = {
            "jobs_scored": len(jobs),
            "alerts": int(predictions["alert"].sum()),
            "min_score": float(scores.min()),
            "max_score": float(scores.max()),
        }
        info = predictor.model_info
        return [
            PredictionResponse(
                job_run_id=job.job_run_id,
                request_id=request.state.request_id,
                risk_score=float(row.score),
                alert_threshold=predictor.threshold,
                alert=bool(row.alert),
                risk_level="ABOVE_THRESHOLD" if row.alert else "BELOW_THRESHOLD",
                model_version=app.state.model_version,
                **info,
                main_risk_factors=(
                    explanation["factors"]
                    if explanation is not None
                    else []
                ),
                explanation_status=(
                    "shap_local"
                    if explanation is not None
                    else "not_available"
                ),
                recommended_checks=recommended_checks(
                    job.features,
                    bool(row.alert),
                ),
                explanation_note=EXPLANATION_NOTE,
            )
            for job, row, explanation in zip(
                jobs,
                predictions.itertuples(index=False),
                explanations,
                strict=True,
            )
        ]

    @app.get("/health", response_model=HealthResponse)
    def health():
        predictor = get_predictor()
        return HealthResponse(
            model_version=app.state.model_version,
            model_status=predictor.model_info["model_status"], api_version=API_VERSION,
        )

    @app.get("/model-info", response_model=ModelInfoResponse)
    def model_info():
        predictor = get_predictor()
        return ModelInfoResponse(
            **predictor.model_info,
            model_version=app.state.model_version,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            feature_columns=predictor.feature_columns,
            feature_dtypes=predictor.feature_dtypes,
            input_schema=JobFeatures.model_json_schema(),
            alert_threshold=predictor.threshold,
            max_batch_size=MAX_BATCH_SIZE,
            explanation_status=(
                "shap_local"
                if predictor.explanation_available
                else "not_available"
            ),
        )

    @app.post("/predict", response_model=PredictionResponse)
    def predict(payload: PredictRequest, request: Request):
        get_predictor()
        check_version(payload.expected_model_version)
        return score_jobs([payload], request)[0]

    @app.post("/predict/batch", response_model=BatchPredictionResponse)
    def predict_batch(payload: BatchPredictRequest, request: Request):
        get_predictor()
        check_version(payload.expected_model_version)
        predictions = score_jobs(payload.jobs, request)
        return BatchPredictionResponse(
            request_id=request.state.request_id,
            model_version=app.state.model_version,
            total=len(predictions), alerts=sum(item.alert for item in predictions),
            predictions=predictions,
        )

    app.include_router(rag_router)
    return app


app = create_app()
