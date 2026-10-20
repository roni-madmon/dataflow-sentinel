"""Fail-fast orchestration for the DataFlow Sentinel data pipeline."""

import argparse
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class PipelineStep:
    name: str
    command: tuple[str, ...]


class PipelineStepError(RuntimeError):
    """Raised when one pipeline stage fails."""


def dbt_executable() -> str:
    candidate = (
        Path(sys.executable).parent
        / ("dbt.exe" if sys.platform == "win32" else "dbt")
    )

    if candidate.is_file():
        return str(candidate)

    return "dbt"


def build_steps() -> list[PipelineStep]:
    return [
        PipelineStep(
            name="Bronze ingestion",
            command=(
                sys.executable,
                str(
                    ROOT
                    / "src"
                    / "ingestion"
                    / "ingest_batch_tasks.py"
                ),
            ),
        ),
        PipelineStep(
            name="PostgreSQL staging load",
            command=(
                sys.executable,
                str(
                    ROOT
                    / "src"
                    / "ingestion"
                    / "load_bronze_to_postgres.py"
                ),
                "--replace",
            ),
        ),
        PipelineStep(
            name="dbt build and tests",
            command=(
                dbt_executable(),
                "build",
                "--project-dir",
                str(
                    ROOT
                    / "dbt"
                    / "dataflow_dbt"
                ),
                "--fail-fast",
            ),
        ),
    ]


def run_step(
    step: PipelineStep,
) -> None:

    print()
    print("=" * 72)
    print(f"PIPELINE STEP: {step.name}")
    print("=" * 72)
    print(
        "Command:",
        subprocess.list2cmdline(
            list(step.command)
        ),
    )

    result = subprocess.run(
        list(step.command),
        cwd=ROOT,
        check=False,
    )

    if result.returncode != 0:
        raise PipelineStepError(
            f"{step.name} failed with exit code "
            f"{result.returncode}. "
            "Downstream stages were not executed."
        )

    print(
        f"STEP STATUS: PASS ? {step.name}"
    )


def run_pipeline(
    *,
    execute: bool,
) -> None:

    steps = build_steps()

    print("=" * 72)
    print("DATAFLOW SENTINEL DATA PIPELINE")
    print("=" * 72)

    if not execute:
        print(
            "MODE: DRY RUN ? no commands will be executed."
        )

        for index, step in enumerate(
            steps,
            start=1,
        ):
            print(
                f"{index}. {step.name}"
            )
            print(
                "   "
                + subprocess.list2cmdline(
                    list(step.command)
                )
            )

        print()
        print("DRY RUN STATUS: PASS")
        return

    print(
        "MODE: EXECUTE"
    )
    print(
        "The PostgreSQL stage uses --replace. "
        "The loader is transactional, so an incomplete "
        "replacement must not be committed."
    )

    for step in steps:
        run_step(step)

    print()
    print("=" * 72)
    print("PIPELINE STATUS: PASS")
    print("=" * 72)


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Run the DataFlow Sentinel ingestion, "
            "PostgreSQL load, and dbt build in "
            "fail-fast order."
        )
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Actually execute the pipeline. "
            "Without this flag, only a dry run is shown."
        ),
    )

    return parser.parse_args()


if __name__ == "__main__":

    args = parse_args()

    try:
        run_pipeline(
            execute=args.execute,
        )

    except PipelineStepError as error:
        print()
        print(
            f"PIPELINE STATUS: FAILED ? {error}",
            file=sys.stderr,
        )
        raise SystemExit(1)
