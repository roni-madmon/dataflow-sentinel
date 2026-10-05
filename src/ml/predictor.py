"""Inference for the frozen DataFlow Sentinel HGB V2 experiment.

Load the locally trained model bundle once, then reuse the predictor. Input
contains the 12 already-aggregated Job features, not raw Task records.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from typing import Any
import warnings

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.exceptions import InconsistentVersionWarning
from threadpoolctl import threadpool_limits


_TASK_TYPE = "task_type_group"
_FLAGS = (
    "missing_plan_cpu_flag",
    "missing_plan_mem_flag",
    "missing_instance_num_flag",
)
# Native thread limits are process-wide. Keep overlapping wrapper calls from
# changing and restoring those limits concurrently in a future API process.
_PREDICTION_LOCK = Lock()


class JobFailurePredictor:
    """Predict using a saved pipeline and its Validation-selected threshold.

    bundle_path may point to model_bundle.joblib or its experiment directory.
    Use the same environment as training. The bundle is a locally produced,
    trusted project artifact; loading user-uploaded model files is not an API.
    """

    def __init__(self, bundle_path: str | Path, *, max_threads: int = 4):
        if isinstance(max_threads, bool) or not isinstance(max_threads, int) or max_threads < 1:
            raise ValueError("max_threads must be a positive integer.")

        path = Path(bundle_path).expanduser()
        if path.is_dir():
            path = path / "model_bundle.joblib"
        if not path.is_file():
            raise FileNotFoundError(f"Model bundle not found: {path}")

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", InconsistentVersionWarning)
                bundle = joblib.load(path)
        except InconsistentVersionWarning as exc:
            raise RuntimeError(
                "The model's scikit-learn version differs from this environment. "
                "Use the training environment recorded in metadata.json."
            ) from exc

        if not isinstance(bundle, dict) or not {"pipeline", "metadata"}.issubset(bundle):
            raise ValueError("Expected a bundle with 'pipeline' and 'metadata' keys.")

        metadata = bundle["metadata"]
        required = {"feature_columns", "feature_dtypes", "threshold", "positive_class",
                    "model_name", "created_at_utc"}
        if not isinstance(metadata, dict) or not required.issubset(metadata):
            raise ValueError("The model bundle has incomplete inference metadata.")

        saved_version = metadata.get("versions", {}).get("scikit-learn")
        if saved_version and saved_version != sklearn.__version__:
            raise RuntimeError(
                f"Expected scikit-learn {saved_version}; found {sklearn.__version__}."
            )

        self._pipeline = bundle["pipeline"]
        self._columns = list(metadata["feature_columns"])
        self._dtypes = dict(metadata["feature_dtypes"])
        expected_fields = {_TASK_TYPE, "task_count", "total_instances", *_FLAGS}
        if (
            len(self._columns) != 12
            or len(set(self._columns)) != 12
            or not expected_fields.issubset(self._columns)
            or set(self._dtypes) != set(self._columns)
        ):
            raise ValueError("The bundle does not contain the expected V2 feature schema.")
        if list(self._pipeline.feature_names_in_) != self._columns:
            raise ValueError("Feature metadata differs from the fitted pipeline schema.")

        self._threshold = float(metadata["threshold"])
        if not np.isfinite(self._threshold) or not 0 <= self._threshold <= 1:
            raise ValueError("The saved threshold must be finite and between 0 and 1.")

        positive_indices = np.flatnonzero(
            np.asarray(self._pipeline.classes_) == metadata["positive_class"]
        )
        if len(positive_indices) != 1:
            raise ValueError("The saved positive class is absent or ambiguous.")
        self._positive_index = int(positive_indices[0])
        self._max_threads = max_threads
        self._model_info = {
            "model_name": metadata["model_name"],
            "model_created_at_utc": metadata["created_at_utc"],
            "model_status": metadata.get("status", "experimental"),
            "score_is_calibrated": False,
        }

    @property
    def threshold(self) -> float:
        """The full-precision threshold frozen before Test evaluation."""
        return self._threshold

    @property
    def feature_columns(self) -> list[str]:
        """A copy of the required input columns in their training order."""
        return self._columns.copy()

    @property
    def feature_dtypes(self) -> dict[str, str]:
        """The saved input precision, for API schema discovery."""
        return self._dtypes.copy()

    @property
    def model_info(self) -> dict[str, Any]:
        """Public model identity and score interpretation."""
        return self._model_info.copy()

    def _prepare_features(self, features: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(features, pd.DataFrame):
            raise TypeError("predict_batch expects a pandas DataFrame.")
        if features.empty:
            raise ValueError("At least one Job is required.")
        if not features.columns.is_unique:
            raise ValueError("Duplicate feature columns are not supported.")

        missing = [name for name in self._columns if name not in features.columns]
        extra = [str(name) for name in features.columns if name not in self._columns]
        if missing or extra:
            raise ValueError(f"Feature schema mismatch. Missing: {missing}; extra: {extra}")

        data = features.loc[:, self._columns].copy()
        numeric_columns = [name for name in self._columns if name != _TASK_TYPE]
        try:
            numeric = data[numeric_columns].apply(pd.to_numeric, errors="raise")
            if any(pd.api.types.is_complex_dtype(dtype) for dtype in numeric.dtypes):
                raise ValueError("Complex numbers are not supported.")
            values = numeric.to_numpy(dtype=np.float64, na_value=np.nan)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Numeric features must contain real numbers or missing values.") from exc
        if np.isinf(values).any():
            raise ValueError("Numeric features cannot contain infinity.")
        data[numeric_columns] = values

        for name in _FLAGS:
            if not data[name].isin([0, 1]).all():
                raise ValueError(f"{name} must be 0 or 1 and cannot be missing.")

        tasks = data["task_count"]
        if tasks.isna().any() or (tasks < 1).any() or (tasks % 1 != 0).any():
            raise ValueError("task_count must be a positive whole number.")
        instances = data["total_instances"].dropna()
        if (instances < 0).any() or (instances % 1 != 0).any():
            raise ValueError("total_instances must be a non-negative whole number or missing.")

        types = data[_TASK_TYPE]
        if types.isna().any() or not types.map(
            lambda value: isinstance(value, str) and bool(value.strip()) and value == value.strip()
        ).all():
            raise ValueError("task_type_group must contain non-empty, trimmed strings.")

        # Restore training precision before the fitted ColumnTransformer runs.
        # This includes float32 rounding for the original nine features.
        for name in numeric_columns:
            dtype = np.dtype(self._dtypes[name])
            if dtype.kind not in "fiu":
                raise ValueError(f"Unsupported numeric dtype for {name}: {dtype}")
            limits = np.finfo(dtype) if dtype.kind == "f" else np.iinfo(dtype)
            if (data[name] < limits.min).any() or (data[name] > limits.max).any():
                raise ValueError(f"{name} is outside the range of {dtype}.")
            data[name] = data[name].astype(dtype)

        # Keep new string categories available to the fitted OrdinalEncoder;
        # it already maps unseen categories to NaN.
        data[_TASK_TYPE] = types.astype("category")
        return data

    def predict_batch(self, features: pd.DataFrame) -> pd.DataFrame:
        """Return score, threshold, and alert, preserving input row order/index."""
        prepared = self._prepare_features(features)
        with _PREDICTION_LOCK:
            with threadpool_limits(limits=self._max_threads):
                scores = self._pipeline.predict_proba(prepared)[:, self._positive_index]
        if not np.isfinite(scores).all():
            raise RuntimeError("The model returned non-finite scores.")
        return pd.DataFrame(
            {
                "score": scores,
                "threshold": self._threshold,
                "alert": scores >= self._threshold,
            },
            index=features.index,
        )

    def predict_one(self, features: Mapping[str, Any]) -> dict[str, Any]:
        """Return one JSON-compatible prediction plus model identity."""
        if not isinstance(features, Mapping):
            raise TypeError("predict_one expects a mapping of feature names to values.")
        result = self.predict_batch(pd.DataFrame([dict(features)])).iloc[0]
        return {
            **self._model_info,
            "score": float(result["score"]),
            "threshold": self._threshold,
            "alert": bool(result["alert"]),
        }
