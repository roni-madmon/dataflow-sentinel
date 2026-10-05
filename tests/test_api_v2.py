"""FastAPI contract and inference integration tests using a real tiny HGB."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import test_job_failure_predictor_v2 as fixtures
from api.app.main import create_app
from api.app.schemas import FEATURE_SCHEMA_VERSION


class ApiV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = fixtures.JobFailurePredictorTests
        cls.fixture.setUpClass()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDownClass()

    def setUp(self):
        self.app = create_app(self.fixture.path)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def payload(self, row=4, job_id="demo-job-001"):
        features = self.fixture.X.iloc[[row]].astype(object)
        features = features.where(pd.notna(features), None).iloc[0].to_dict()
        return {"job_run_id": job_id, "features": features}

    def test_health_and_model_info(self):
        health = self.client.get("/health")
        info = self.client.get("/model-info")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.json()["model_loaded"])
        self.assertEqual(info.status_code, 200)
        self.assertEqual(info.json()["model_version"], health.json()["model_version"])
        self.assertEqual(info.json()["feature_columns"], list(self.fixture.X.columns))
        self.assertEqual(info.json()["alert_threshold"], self.fixture.metadata["threshold"])
        self.assertEqual(info.json()["feature_schema_version"], FEATURE_SCHEMA_VERSION)
        self.assertEqual(len(info.json()["input_schema"]["required"]), 12)
        self.assertFalse(info.json()["score_is_calibrated"])

    def test_single_matches_frozen_pipeline_and_excludes_identifier(self):
        response = self.client.post("/predict", json=self.payload())
        self.assertEqual(response.status_code, 200, response.text)
        output = response.json()
        self.assertAlmostEqual(output["risk_score"], self.fixture.expected[4], places=12)
        self.assertEqual(output["alert_threshold"], self.fixture.metadata["threshold"])
        self.assertEqual(output["alert"], bool(self.fixture.expected[4] >= output["alert_threshold"]))
        self.assertEqual(output["request_id"], response.headers["X-Request-ID"])
        self.assertEqual(output["main_risk_factors"], [])
        self.assertEqual(output["explanation_status"], "not_available")
        self.assertNotIn("risk_probability", output)
        changed_id = self.client.post("/predict", json=self.payload(job_id="another-id")).json()
        self.assertEqual(changed_id["risk_score"], output["risk_score"])
        self.assertNotEqual(changed_id["request_id"], output["request_id"])

    def test_batch_preserves_job_order_and_matches_single_predictions(self):
        jobs = [self.payload(7, "job-B"), self.payload(0, "job-A")]
        result = self.client.post("/predict/batch", json={"jobs": jobs})
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual([item["job_run_id"] for item in body["predictions"]], ["job-B", "job-A"])
        for job, prediction in zip(jobs, body["predictions"], strict=True):
            single = self.client.post("/predict", json=job).json()
            self.assertEqual(prediction["risk_score"], single["risk_score"])
            self.assertEqual(prediction["alert"], single["alert"])
        self.assertEqual(body["alerts"], sum(p["alert"] for p in body["predictions"]))

    def test_bad_types_missing_fields_and_extra_features_return_422(self):
        cases = []
        missing = self.payload()
        del missing["features"]["task_count"]
        cases.append(missing)
        extra = self.payload()
        extra["features"]["failed_job"] = 1
        cases.append(extra)
        for name, value in [
            ("task_count", 1.5), ("task_count", True),
            ("missing_plan_mem_flag", "0"), ("mean_task_plan_mem", "0.1"),
            ("mean_task_plan_cpu", 1e100), ("task_type_group", " "),
            ("total_instances", -2), ("missing_instance_num_flag", 256),
        ]:
            payload = self.payload()
            payload["features"][name] = value
            cases.append(payload)
        for payload in cases:
            with self.subTest(payload=payload):
                response = self.client.post("/predict", json=payload)
                self.assertEqual(response.status_code, 422, response.text)

    def test_non_finite_numbers_return_422_without_echoing_invalid_json(self):
        for value in [float("nan"), float("inf"), -float("inf")]:
            payload = self.payload()
            payload["features"]["mean_task_plan_cpu"] = value
            response = self.client.post(
                "/predict", content=json.dumps(payload), headers={"Content-Type": "application/json"},
            )
            self.assertEqual(response.status_code, 422, response.text)
            json.dumps(response.json(), allow_nan=False)

    def test_missing_values_need_flags_and_checks_are_not_attributions(self):
        payload = self.payload()
        payload["features"]["mean_task_plan_cpu"] = None
        self.assertEqual(self.client.post("/predict", json=payload).status_code, 422)
        payload["features"]["missing_plan_cpu_flag"] = 1
        response = self.client.post("/predict", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(any("CPU" in check for check in response.json()["recommended_checks"]))
        self.assertEqual(response.json()["main_risk_factors"], [])

    def test_unknown_task_type_is_handled_by_the_saved_encoder(self):
        payload = self.payload()
        payload["features"]["task_type_group"] = "type_new"
        response = self.client.post("/predict", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(np.isfinite(response.json()["risk_score"]))

    def test_schema_and_model_version_mismatches_are_clear(self):
        payload = self.payload()
        payload["schema_version"] = "unknown-schema"
        self.assertEqual(self.client.post("/predict", json=payload).status_code, 422)
        payload = self.payload()
        payload["expected_model_version"] = "different-model"
        self.assertEqual(self.client.post("/predict", json=payload).status_code, 409)
        payload["expected_model_version"] = self.client.get("/model-info").json()["model_version"]
        self.assertEqual(self.client.post("/predict", json=payload).status_code, 200)

    def test_empty_oversize_and_duplicate_id_batches_are_rejected(self):
        cases = [
            {"jobs": []},
            {"jobs": [self.payload(), self.payload()]},
            {"jobs": [self.payload(job_id=f"job-{i}") for i in range(501)]},
        ]
        for payload in cases:
            with self.subTest(size=len(payload["jobs"])):
                self.assertEqual(self.client.post("/predict/batch", json=payload).status_code, 422)

    def test_logs_contain_request_metrics_but_not_raw_payload_or_ids(self):
        with self.assertLogs("dataflow_sentinel.api", level="INFO") as captured:
            response = self.client.post("/predict?private=DO_NOT_LOG", json=self.payload(job_id="PRIVATE_JOB_ID"))
        self.assertEqual(response.status_code, 200)
        logs = "\n".join(captured.output)
        self.assertNotIn("PRIVATE_JOB_ID", logs)
        self.assertNotIn("DO_NOT_LOG", logs)
        self.assertNotIn("task_type_group", logs)
        event = json.loads(captured.records[-1].getMessage())
        self.assertEqual(event["request_id"], response.headers["X-Request-ID"])
        self.assertIn("latency_ms", event)
        self.assertIn("min_score", event)
        self.assertEqual(event["validation_outcome"], "accepted")

    def test_unexpected_errors_are_sanitized(self):
        with patch.object(self.app.state.predictor, "predict_batch", side_effect=RuntimeError("PRIVATE_ERROR_TEXT")):
            with self.assertLogs("dataflow_sentinel.api", level="INFO") as captured:
                response = self.client.post("/predict", json=self.payload())
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("PRIVATE_ERROR_TEXT", response.text)
        self.assertNotIn("PRIVATE_ERROR_TEXT", "\n".join(captured.output))

    def test_health_is_not_ready_without_startup_and_missing_model_fails_startup(self):
        unstarted = TestClient(create_app(self.fixture.path))
        self.addCleanup(unstarted.close)
        self.assertEqual(unstarted.get("/health").status_code, 503)
        with self.assertRaises(FileNotFoundError):
            with TestClient(create_app(self.fixture.directory / "missing.joblib")):
                pass


if __name__ == "__main__":
    unittest.main()
