"""Validated local SHAP explanations for the frozen HGB V2 model."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np
import pandas as pd
import shap
from threadpoolctl import threadpool_limits


_EXPLANATION_LOCK = Lock()
_TASK_TYPE = "task_type_group"


class PermutationShapExplainer:
    """Explain HGB V2 scores with a validated model-agnostic SHAP method.

    Contributions explain movement in the model score relative to the
    Train-background baseline. They are model attributions, not causal
    failure explanations.
    """

    def __init__(
        self,
        pipeline,
        background_path: str | Path,
        feature_columns: list[str],
        feature_dtypes: dict[str, str],
        positive_index: int,
        *,
        max_threads: int = 4,
        seed: int = 42,
    ):
        if (
            isinstance(max_threads, bool)
            or not isinstance(max_threads, int)
            or max_threads < 1
        ):
            raise ValueError(
                "max_threads must be a positive integer."
            )

        path = Path(background_path).expanduser()

        if not path.is_file():
            raise FileNotFoundError(
                f"SHAP background not found: {path}"
            )

        self._pipeline = pipeline
        self._preprocessor = pipeline.named_steps["preprocessor"]
        self._model = pipeline.named_steps["model"]

        self._columns = list(feature_columns)
        self._dtypes = dict(feature_dtypes)
        self._positive_index = int(positive_index)
        self._max_threads = max_threads

        background = pd.read_csv(path)

        if list(background.columns) != self._columns:
            raise ValueError(
                "SHAP background schema differs from "
                "the model feature schema."
            )

        background = self._restore_dtypes(background)

        self._feature_names = [
            name
            .replace("numeric__", "")
            .replace("task_type__", "")
            for name
            in self._preprocessor.get_feature_names_out()
        ]

        if len(self._feature_names) != len(self._columns):
            raise ValueError(
                "Transformed feature count differs from "
                "the model feature count."
            )

        transformed_background = (
            self._preprocessor.transform(background)
        )

        if transformed_background.shape[1] != len(
            self._feature_names
        ):
            raise ValueError(
                "Unexpected transformed SHAP background shape."
            )

        masker = shap.maskers.Independent(
            transformed_background,
            max_samples=len(transformed_background),
        )

        self._explainer = shap.PermutationExplainer(
            self._positive_score,
            masker,
            feature_names=self._feature_names,
            seed=seed,
        )

    def _restore_dtypes(
        self,
        frame: pd.DataFrame,
    ) -> pd.DataFrame:
        data = frame.loc[:, self._columns].copy()

        for name, dtype in self._dtypes.items():

            if name == _TASK_TYPE:
                data[name] = data[name].astype("category")
            else:
                data[name] = data[name].astype(dtype)

        return data

    def _positive_score(
        self,
        transformed,
    ) -> np.ndarray:
        return self._model.predict_proba(
            transformed
        )[:, self._positive_index]

    @staticmethod
    def _display_value(value: Any) -> str | float:
        if pd.isna(value):
            return "missing"

        if isinstance(value, str):
            return value

        if isinstance(value, np.generic):
            value = value.item()

        if isinstance(value, (int, float)):
            return float(value)

        return str(value)

    def explain_prepared(
        self,
        prepared_features: pd.DataFrame,
        *,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Return validated local model attributions for prepared rows."""

        if not isinstance(prepared_features, pd.DataFrame):
            raise TypeError(
                "prepared_features must be a pandas DataFrame."
            )

        if prepared_features.empty:
            raise ValueError(
                "At least one Job is required for explanation."
            )

        if list(prepared_features.columns) != self._columns:
            raise ValueError(
                "Prepared feature schema differs from "
                "the model feature schema."
            )

        if (
            isinstance(top_k, bool)
            or not isinstance(top_k, int)
            or not 1 <= top_k <= len(self._feature_names)
        ):
            raise ValueError(
                "top_k must be between 1 and the feature count."
            )

        transformed = self._preprocessor.transform(
            prepared_features
        )

        max_evals = (
            2 * len(self._feature_names) + 1
        )

        with _EXPLANATION_LOCK:
            with threadpool_limits(
                limits=self._max_threads
            ):
                explanation = self._explainer(
                    transformed,
                    max_evals=max_evals,
                    silent=True,
                )

        values = np.asarray(
            explanation.values,
            dtype=np.float64,
        )

        if values.ndim == 1:
            values = values.reshape(1, -1)

        base_values = np.asarray(
            explanation.base_values,
            dtype=np.float64,
        ).reshape(-1)

        scores = np.asarray(
            self._positive_score(transformed),
            dtype=np.float64,
        )

        reconstructed = (
            base_values
            + values.sum(axis=1)
        )

        if (
            not np.isfinite(values).all()
            or not np.isfinite(base_values).all()
            or not np.isfinite(scores).all()
            or not np.isfinite(reconstructed).all()
        ):
            raise RuntimeError(
                "SHAP returned non-finite explanation values."
            )

        if not np.allclose(
            reconstructed,
            scores,
            rtol=0,
            atol=1e-8,
        ):
            difference = float(
                np.max(
                    np.abs(
                        reconstructed - scores
                    )
                )
            )

            raise RuntimeError(
                "SHAP additivity validation failed. "
                f"Maximum difference: {difference}"
            )

        results = []

        for row_number in range(
            len(prepared_features)
        ):
            ranking = sorted(
                range(len(self._feature_names)),
                key=lambda index: abs(
                    values[row_number, index]
                ),
                reverse=True,
            )

            factors = []

            for index in ranking[:top_k]:
                contribution = float(
                    values[row_number, index]
                )

                if contribution > 0:
                    direction = "higher_score"
                elif contribution < 0:
                    direction = "lower_score"
                else:
                    direction = "neutral"

                feature = self._feature_names[index]

                factors.append(
                    {
                        "feature": feature,
                        "value": self._display_value(
                            prepared_features.iloc[
                                row_number
                            ][feature]
                        ),
                        "shap_value": contribution,
                        "direction": direction,
                    }
                )

            results.append(
                {
                    "model_score": float(
                        scores[row_number]
                    ),
                    "base_score": float(
                        base_values[row_number]
                    ),
                    "reconstructed_score": float(
                        reconstructed[row_number]
                    ),
                    "factors": factors,
                }
            )

        return results
