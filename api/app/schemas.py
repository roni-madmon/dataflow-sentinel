"""Versioned HTTP contracts for the 12-feature HGB V2 model."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator

FEATURE_SCHEMA_VERSION = "hgb-v2-features-v1"
MAX_BATCH_SIZE = 500
Score = Annotated[FiniteFloat, Field(ge=0, le=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class JobFeatures(StrictModel):
    task_count: int = Field(ge=1)
    mean_task_plan_cpu: FiniteFloat | None
    max_task_plan_cpu: FiniteFloat | None
    total_task_plan_cpu: FiniteFloat | None
    mean_task_plan_mem: FiniteFloat | None
    max_task_plan_mem: FiniteFloat | None
    total_task_plan_mem: FiniteFloat | None
    missing_plan_cpu_flag: int = Field(ge=0, le=1)
    missing_plan_mem_flag: int = Field(ge=0, le=1)
    total_instances: int | None = Field(ge=0)
    missing_instance_num_flag: int = Field(ge=0, le=1)
    task_type_group: str = Field(min_length=1, max_length=128)

    @field_validator("*", mode="before")
    @classmethod
    def reject_booleans(cls, value):
        if isinstance(value, bool):
            raise ValueError("Use numeric values or category strings, not booleans.")
        return value

    @field_validator(
        "task_count", "total_instances", "missing_plan_cpu_flag",
        "missing_plan_mem_flag", "missing_instance_num_flag", mode="before",
    )
    @classmethod
    def whole_numbers(cls, value):
        if value is None:
            return value
        if type(value) not in (int, float):
            raise ValueError("A numeric whole number is required.")
        if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
            raise ValueError("A finite whole number is required.")
        # Notebook float32 counts become JSON 1.0; preserve that valid input.
        return int(value)

    @field_validator("task_type_group")
    @classmethod
    def trimmed_type(cls, value):
        if not value.strip() or value != value.strip():
            raise ValueError("task_type_group must be a non-empty trimmed string.")
        return value

    @model_validator(mode="after")
    def check_missing_flags(self):
        for suffix in ("cpu", "mem"):
            values = [getattr(self, f"{prefix}_task_plan_{suffix}") for prefix in ("mean", "max", "total")]
            if any(value is None for value in values) and getattr(self, f"missing_plan_{suffix}_flag") != 1:
                raise ValueError(f"Missing {suffix} values require missing_plan_{suffix}_flag=1.")
        if self.total_instances is None and self.missing_instance_num_flag != 1:
            raise ValueError("Missing total_instances requires missing_instance_num_flag=1.")
        return self


class JobInput(StrictModel):
    job_run_id: str = Field(min_length=1, max_length=200)
    features: JobFeatures

    @field_validator("job_run_id")
    @classmethod
    def trimmed_id(cls, value):
        if not value.strip() or value != value.strip():
            raise ValueError("job_run_id must be a non-empty trimmed string.")
        return value


class PredictRequest(JobInput):
    schema_version: Literal[FEATURE_SCHEMA_VERSION] = FEATURE_SCHEMA_VERSION
    expected_model_version: str | None = Field(default=None, min_length=1, max_length=256)


class BatchPredictRequest(StrictModel):
    jobs: list[JobInput] = Field(min_length=1, max_length=MAX_BATCH_SIZE)
    schema_version: Literal[FEATURE_SCHEMA_VERSION] = FEATURE_SCHEMA_VERSION
    expected_model_version: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [job.job_run_id for job in self.jobs]
        if len(ids) != len(set(ids)):
            raise ValueError("job_run_id must be unique within a batch.")
        return self


class PredictionResponse(StrictModel):
    job_run_id: str
    request_id: str
    risk_score: Score
    alert_threshold: Score
    alert: bool
    risk_level: Literal["ABOVE_THRESHOLD", "BELOW_THRESHOLD"]
    model_version: str
    model_name: str
    model_created_at_utc: str
    model_status: str
    score_is_calibrated: Literal[False] = False
    main_risk_factors: list[dict[str, str | float]] = Field(default_factory=list)
    explanation_status: Literal["not_available", "shap_local"] = "not_available"
    recommended_checks: list[str]
    explanation_note: str


class BatchPredictionResponse(StrictModel):
    request_id: str
    model_version: str
    total: int
    alerts: int
    predictions: list[PredictionResponse]


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
    model_loaded: Literal[True] = True
    model_version: str
    model_status: str
    api_version: str


class ModelInfoResponse(StrictModel):
    model_version: str
    model_name: str
    model_created_at_utc: str
    model_status: str
    score_is_calibrated: Literal[False] = False
    feature_schema_version: str
    feature_columns: list[str]
    feature_dtypes: dict[str, str]
    input_schema: dict
    alert_threshold: Score
    max_batch_size: int
    feature_availability_status: Literal["unverified_pre_run"] = "unverified_pre_run"
    explanation_status: Literal["not_available", "shap_local"] = "not_available"
