"""Tests for fail-fast data-pipeline orchestration."""

import subprocess
import unittest
from unittest.mock import patch

from scripts.run_data_pipeline import (
    PipelineStepError,
    build_steps,
    run_pipeline,
)


class DataPipelineOrchestrationTests(
    unittest.TestCase
):

    def test_expected_pipeline_order(self):

        steps = build_steps()

        self.assertEqual(
            [step.name for step in steps],
            [
                "Bronze ingestion",
                "PostgreSQL staging load",
                "dbt build and tests",
            ],
        )

        self.assertIn(
            "--replace",
            steps[1].command,
        )

        self.assertIn(
            "--fail-fast",
            steps[2].command,
        )

    @patch(
        "scripts.run_data_pipeline.subprocess.run"
    )
    def test_dry_run_executes_nothing(
        self,
        mocked_run,
    ):

        run_pipeline(
            execute=False,
        )

        mocked_run.assert_not_called()

    @patch(
        "scripts.run_data_pipeline.subprocess.run"
    )
    def test_success_runs_all_steps(
        self,
        mocked_run,
    ):

        mocked_run.return_value = (
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
            )
        )

        run_pipeline(
            execute=True,
        )

        self.assertEqual(
            mocked_run.call_count,
            3,
        )

    @patch(
        "scripts.run_data_pipeline.subprocess.run"
    )
    def test_failure_blocks_downstream_steps(
        self,
        mocked_run,
    ):

        mocked_run.side_effect = [
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=7,
            ),
        ]

        with self.assertRaisesRegex(
            PipelineStepError,
            "Downstream stages were not executed",
        ):
            run_pipeline(
                execute=True,
            )

        self.assertEqual(
            mocked_run.call_count,
            2,
        )


if __name__ == "__main__":
    unittest.main()
