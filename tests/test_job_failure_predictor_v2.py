"""Contract tests using a small, real sklearn pipeline, without project data."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder
from threadpoolctl import threadpool_limits

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ml.predictor import JobFailurePredictor


class JobFailurePredictorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name)
        n = 96
        instances = np.tile([1, 2, 4, 128], n // 4).astype(np.float64)
        types = np.tile(["type_1", "type_10", "type_11"], n // 3)
        cls.X = pd.DataFrame({
            "task_count": np.ones(n),
            "mean_task_plan_cpu": np.full(n, 100),
            "max_task_plan_cpu": np.full(n, 100),
            "total_task_plan_cpu": np.full(n, 100),
            "mean_task_plan_mem": np.full(n, 0.1),
            "max_task_plan_mem": np.full(n, 0.1),
            "total_task_plan_mem": np.full(n, 0.1),
            "missing_plan_cpu_flag": np.zeros(n),
            "missing_plan_mem_flag": np.zeros(n),
            "total_instances": instances,
            "missing_instance_num_flag": np.zeros(n, dtype=np.int8),
            "task_type_group": pd.Categorical(types),
        })
        original_features = list(cls.X.columns[:9])
        cls.X[original_features] = cls.X[original_features].astype(np.float32)
        cpu_columns = original_features[1:4]
        cls.X.loc[::11, cpu_columns] = np.nan
        cls.X.loc[::11, "missing_plan_cpu_flag"] = 1
        numeric_columns = list(cls.X.columns[:-1])
        y = ((types == "type_10") | (instances > 100)).astype(np.int8)

        cls.pipeline = Pipeline([
            ("preprocessor", ColumnTransformer([
                ("numeric", "passthrough", numeric_columns),
                ("task_type", OrdinalEncoder(
                    handle_unknown="use_encoded_value",
                    unknown_value=np.nan,
                    dtype=np.float64,
                ), ["task_type_group"]),
            ])),
            ("model", HistGradientBoostingClassifier(
                max_iter=12, max_leaf_nodes=7, min_samples_leaf=2,
                categorical_features=[len(numeric_columns)],
                early_stopping=False, random_state=42,
            )),
        ])
        with threadpool_limits(limits=2):
            cls.pipeline.fit(cls.X, y)
            cls.expected = cls.pipeline.predict_proba(cls.X)[:, 1]

        cls.metadata = {
            "feature_columns": list(cls.X.columns),
            "feature_dtypes": {name: str(dtype) for name, dtype in cls.X.dtypes.items()},
            "threshold": 0.5000000000000001,
            "positive_class": 1,
            "model_name": "HGB V2 fixture",
            "created_at_utc": "2026-10-02T00:00:00+00:00",
            "status": "experimental",
            "versions": {"scikit-learn": sklearn.__version__},
        }
        cls.path = cls.directory / "model_bundle.joblib"
        joblib.dump({"pipeline": cls.pipeline, "metadata": cls.metadata}, cls.path)
        cls.predictor = JobFailurePredictor(cls.directory, max_threads=2)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_batch_matches_pipeline_with_shuffled_columns_and_preserves_index(self):
        data = self.X.copy()
        data.index = pd.Index(np.arange(len(data)) * 3, name="source_row")
        data = data.loc[:, list(reversed(data.columns))]
        before = data.copy(deep=True)
        result = self.predictor.predict_batch(data)
        np.testing.assert_allclose(result["score"], self.expected, rtol=0, atol=1e-12)
        np.testing.assert_array_equal(result["alert"], self.expected >= self.metadata["threshold"])
        pd.testing.assert_index_equal(result.index, data.index)
        pd.testing.assert_frame_equal(data, before)

    def test_one_job_is_json_compatible_and_matches_batch(self):
        result = self.predictor.predict_one(self.X.iloc[4].to_dict())
        self.assertAlmostEqual(result["score"], self.expected[4], places=12)
        self.assertEqual(result["threshold"], self.metadata["threshold"])
        self.assertIsInstance(result["alert"], bool)
        self.assertFalse(result["score_is_calibrated"])
        self.assertEqual(result["model_created_at_utc"], self.metadata["created_at_utc"])
        json.dumps(result, allow_nan=False)

    def test_missing_numeric_values_and_unseen_category_use_fitted_pipeline(self):
        data = self.X.iloc[:4].copy()
        data["task_type_group"] = data["task_type_group"].astype(object)
        data.iloc[0, data.columns.get_loc("task_type_group")] = "type_unseen"
        data.loc[data.index[1], "total_instances"] = np.nan
        data.loc[data.index[1], "missing_instance_num_flag"] = 1
        data["task_type_group"] = data["task_type_group"].astype("category")
        with threadpool_limits(limits=2):
            expected = self.pipeline.predict_proba(data)[:, 1]
        actual = self.predictor.predict_batch(data)
        np.testing.assert_allclose(actual["score"], expected, rtol=0, atol=1e-12)

    def test_schema_errors_are_rejected(self):
        duplicate = pd.concat([self.X.iloc[:1], self.X.iloc[:1][["task_count"]]], axis=1)
        cases = [
            self.X.iloc[:1].drop(columns="total_instances"),
            self.X.iloc[:1].assign(failed_job=1),
            duplicate,
            self.X.iloc[:0],
        ]
        for data in cases:
            with self.subTest(columns=list(data.columns), rows=len(data)):
                with self.assertRaises(ValueError):
                    self.predictor.predict_batch(data)

    def test_invalid_values_and_float32_overflow_are_rejected(self):
        cases = [
            ("task_count", 0),
            ("task_count", 1.5),
            ("task_count", None),
            ("total_instances", -1),
            ("total_instances", 2.5),
            ("missing_instance_num_flag", 256),
            ("missing_plan_cpu_flag", None),
            ("mean_task_plan_cpu", float("inf")),
            ("mean_task_plan_cpu", 1e100),
            ("mean_task_plan_cpu", "invalid"),
            ("task_type_group", None),
            ("task_type_group", " type_10 "),
        ]
        for name, value in cases:
            with self.subTest(feature=name, value=value):
                row = self.X.iloc[4].to_dict()
                row[name] = value
                with self.assertRaises(ValueError):
                    self.predictor.predict_one(row)

    def test_threshold_is_full_precision_and_comparison_is_inclusive(self):
        row = self.X.iloc[[4]]
        with threadpool_limits(limits=2):
            score = float(self.pipeline.predict_proba(row)[0, 1])
        for threshold, expected_alert in [(score, True), (np.nextafter(score, np.inf), False)]:
            with self.subTest(threshold=threshold):
                metadata = deepcopy(self.metadata)
                metadata["threshold"] = float(threshold)
                path = self.directory / "boundary_bundle.joblib"
                joblib.dump({"pipeline": self.pipeline, "metadata": metadata}, path)
                predictor = JobFailurePredictor(path, max_threads=2)
                result = predictor.predict_one(row.iloc[0].to_dict())
                self.assertEqual(result["threshold"], float(threshold))
                self.assertEqual(result["alert"], expected_alert)


if __name__ == "__main__":
    unittest.main()
