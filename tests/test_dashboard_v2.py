"""Meaningful report, business calculation, CSV and Streamlit workflow tests."""

from copy import deepcopy
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dashboard.client import ApiError
from dashboard.data import FEATURES, load_report, normalize_metrics, parse_jobs_csv, simulate

THRESHOLD = 0.9696205830070223
METADATA = {"model_name": "HGB V2", "created_at_utc": "2026-10-02T10:48:01.398392+00:00",
            "status": "experimental", "threshold": THRESHOLD,
            "rows": {"train": 2912014, "validation": 623763, "test": 624196},
            "test_label_time_exclusions": {"missing": 3, "invalid": 0},
            "limitations": ["Pre-run feature availability is assumed."]}
VERSION = f"{METADATA['model_name']}@{METADATA['created_at_utc']}"
INFO = {"feature_columns": FEATURES, "model_version": VERSION, "model_name": "HGB V2",
        "model_status": "experimental", "alert_threshold": THRESHOLD,
        "max_batch_size": 500, "score_is_calibrated": False}
METRICS = [
    {"model": "HGB V2", "split": "Validation", "AP": .5169, "threshold": THRESHOLD,
     "alerts": 45910, "true_alerts": 24056, "false_alerts": 21854, "missed_failures": 2607},
    {"model": "HGB V2", "split": "Test", "AP": .1948, "threshold": THRESHOLD,
     "alerts": 19826, "true_alerts": 2448, "false_alerts": 17378, "missed_failures": 2342},
]


def write_fixture(directory):
    (directory / "metadata.json").write_text(json.dumps(METADATA), encoding="utf-8")
    pd.DataFrame(METRICS).to_csv(directory / "validation_test_metrics.csv", index=False)
    for filename in ("error_analysis_by_task_type.csv", "error_analysis_by_task_type_and_instances.csv"):
        pd.DataFrame([{"split": "Test", "task_type_group": "type_10", "jobs": 33429,
                       "failures": 1946, "false_alerts": 17375, "missed_failures": 31}]).to_csv(directory / filename, index=False)


class DashboardDataTests(unittest.TestCase):
    def test_saved_counts_reproduce_reported_test_population(self):
        frame = normalize_metrics(pd.DataFrame(METRICS), METADATA)
        test = frame.loc[frame["split"] == "Test"].iloc[0]
        self.assertEqual(test["jobs"], 624196)
        self.assertEqual(test["failures"], 4790)
        self.assertEqual(test["true_negatives"], 602028)
        self.assertAlmostEqual(test["precision"], .12347422576414809)
        self.assertAlmostEqual(test["recall"], .5110647181628393)
        self.assertEqual(test["ap"], .1948)

    def test_index_export_and_derived_true_alerts(self):
        frame = pd.DataFrame(METRICS).drop(columns="true_alerts").rename(columns={"split": "Unnamed: 0"})
        result = normalize_metrics(frame, METADATA)
        self.assertEqual(result["true_alerts"].tolist(), [24056, 2448])

    def test_rejects_inconsistent_counts_threshold_and_model_identity(self):
        for column, value in [("alerts", 1), ("false_alerts", -1), ("threshold", .5)]:
            frame = pd.DataFrame(METRICS)
            frame.loc[0, column] = value
            with self.subTest(column=column), self.assertRaises(ValueError):
                normalize_metrics(frame, METADATA)
        with tempfile.TemporaryDirectory() as path:
            write_fixture(Path(path))
            with self.assertRaisesRegex(ValueError, "different model"):
                load_report(path, "OTHER_MODEL")

    def test_csv_preserves_identifier_and_missing_values(self):
        data = (ROOT / "examples/dashboard_jobs_template.csv").read_text().replace("demo-job-001", "000123")
        jobs = parse_jobs_csv(data.encode())
        self.assertEqual(jobs[0]["job_run_id"], "000123")
        self.assertEqual(jobs[0]["features"]["task_type_group"], "type_10")
        self.assertEqual(list(jobs[0]["features"]), FEATURES)
        frame = pd.read_csv(StringIO(data), dtype={"job_run_id": str})
        frame["mean_task_plan_cpu"] = None
        frame["missing_plan_cpu_flag"] = 1
        self.assertIsNone(parse_jobs_csv(frame.to_csv(index=False).encode())[0]["features"]["mean_task_plan_cpu"])

    def test_csv_rejects_extra_labels_duplicate_ids_and_nonfinite_values(self):
        frame = pd.read_csv(ROOT / "examples/dashboard_jobs_template.csv")
        cases = [frame.assign(failed_job=1), pd.concat([frame.iloc[:1], frame.iloc[:1]]), frame.assign(task_count=float("inf"))]
        for case in cases:
            with self.subTest(columns=list(case)), self.assertRaises(ValueError):
                parse_jobs_csv(case.to_csv(index=False).encode())
        with self.assertRaisesRegex(ValueError, "At most"):
            parse_jobs_csv(frame.to_csv(index=False).encode(), max_rows=1)

    def test_simulator_charges_every_alert_and_retains_negative_benefit(self):
        result = simulate(624196, 19826, 2448, 17378, 2342, 100, 10, .25)
        self.assertEqual(result["prevented_failures"], 612)
        self.assertEqual(result["investigation_cost"], 198260)
        self.assertEqual(result["gross_benefit"], 61200)
        self.assertEqual(result["net_benefit"], -137060)
        self.assertAlmostEqual(result["net_per_1000_jobs"], -219.57846573832578)
        self.assertGreater(result["break_even_prevention"], .8)
        self.assertEqual(result["remaining_failures"], 4178)

    def test_simulator_zero_cases_and_invalid_assumptions(self):
        zero = simulate(100, 0, 0, 0, 10, 100, 0, .5)
        self.assertEqual(zero["net_benefit"], 0)
        self.assertIsNone(zero["roi"])
        self.assertIsNone(zero["break_even_prevention"])
        for rate in (-.1, 1.1, float("nan")):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                simulate(100, 5, 2, 3, 1, 100, 10, rate)


class DashboardUiTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        write_fixture(self.directory)
        self.env = patch.dict(os.environ, {"SENTINEL_MODEL_PATH": str(self.directory), "SENTINEL_API_URL": "http://127.0.0.1:8000"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.calls = []

        def fake_api(base_url, path, payload=None, **kwargs):
            self.calls.append((path, payload))
            if path == "/model-info":
                return deepcopy(INFO)
            if path == "/predict":
                self.assertEqual(payload["expected_model_version"], VERSION)
                self.assertEqual(set(payload["features"]), set(FEATURES))
                return {"job_run_id": payload["job_run_id"], "request_id": "request-001", "risk_score": THRESHOLD,
                        "alert_threshold": THRESHOLD, "alert": True, "model_version": VERSION,
                        "recommended_checks": ["Review planned resources."], "explanation_status": "not_available"}
            raise AssertionError(path)
        self.mock = patch("dashboard.client.call_api", side_effect=fake_api)
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.at = AppTest.from_file(str(ROOT / "dashboard/app.py"), default_timeout=15).run()

    def assert_clean(self):
        self.assertEqual(len(self.at.exception), 0, str(self.at.exception))

    def go(self, page):
        self.at.radio(key="page").set_value(page).run()
        self.assert_clean()

    def test_all_six_pages_render_with_saved_reports(self):
        self.assert_clean()
        for page in ["Score jobs", "Alert queue", "Model performance", "Business simulator", "Data quality"]:
            with self.subTest(page=page):
                self.go(page)
        self.assertTrue(any("Pre-run" in str(c.value) or "pre-run" in str(c.value) for c in self.at.info))

    def test_single_prediction_queue_and_no_scoring_on_rerun(self):
        self.go("Score jobs")
        next(b for b in self.at.button if b.label == "Score job").click().run()
        self.assert_clean()
        self.assertEqual(len(self.at.session_state["history"]), 1)
        self.assertTrue(self.at.session_state["history"][0]["alert"])
        self.assertEqual(self.at.session_state["history"][0]["_source"], "Synthetic demo")
        self.go("Alert queue")
        self.assertTrue(any(m.value == "Review" for m in self.at.metric))
        self.at.run()
        self.assertEqual(sum(path == "/predict" for path, _ in self.calls), 1)

    def test_simulator_ui_changes_and_invalid_scenario_order(self):
        self.go("Business simulator")
        self.assertTrue(any(m.value == "-137,060.00" for m in self.at.metric))
        next(s for s in self.at.slider if s.label == "Conservative prevention (%)").set_value(90).run()
        self.assert_clean()
        self.assertTrue(any("increasing order" in e.value for e in self.at.error))

    def test_offline_api_preserves_report_pages_and_disables_scoring(self):
        self.mock.stop()
        with patch("dashboard.client.call_api", side_effect=ApiError("Cannot reach the API.")):
            self.go("Model performance")
            self.assertGreater(len(self.at.dataframe), 0)
            self.go("Score jobs")
            self.assertTrue(next(b for b in self.at.button if b.label == "Score job").disabled)


if __name__ == "__main__":
    unittest.main()
