from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


COLUMNS = [
    "task_name",
    "instance_num",
    "job_name",
    "task_type",
    "status",
    "start_time",
    "end_time",
    "plan_cpu",
    "plan_mem",
]

DTYPES = {
    "task_name": "string",
    "instance_num": "Int64",
    "job_name": "string",
    "task_type": "Int64",
    "status": "string",
    "start_time": "Int64",
    "end_time": "Int64",
    "plan_cpu": "Float64",
    "plan_mem": "Float64",
}

ALLOWED_STATUSES = {
    "Terminated",
    "Running",
    "Failed",
    "Waiting",
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_SOURCE = (
    PROJECT_ROOT / "data" / "source" / "batch_task.csv"
)

DEFAULT_OUTPUT = (
    PROJECT_ROOT / "data" / "raw" / "batch_tasks"
)


def calculate_sha256(
    file_path: Path,
    block_size: int = 1024 * 1024,
) -> str:
    """Calculate SHA-256 without loading the entire file into memory."""

    sha256 = hashlib.sha256()

    with file_path.open("rb") as file:
        while True:
            block = file.read(block_size)

            if not block:
                break

            sha256.update(block)

    return sha256.hexdigest()


def load_manifest(manifest_path: Path) -> dict | None:
    """Load an existing ingestion manifest if it exists."""

    if not manifest_path.exists():
        return None

    with manifest_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def validate_chunk(
    chunk: pd.DataFrame,
    chunk_number: int,
) -> None:
    """Validate basic schema and critical fields."""

    if list(chunk.columns) != COLUMNS:
        raise ValueError(
            f"Chunk {chunk_number}: unexpected columns."
        )

    if chunk["job_name"].isna().any():
        raise ValueError(
            f"Chunk {chunk_number}: missing job_name detected."
        )

    if chunk["task_name"].isna().any():
        raise ValueError(
            f"Chunk {chunk_number}: missing task_name detected."
        )

    unexpected_statuses = (
        set(chunk["status"].dropna().unique())
        - ALLOWED_STATUSES
    )

    if unexpected_statuses:
        raise ValueError(
            f"Chunk {chunk_number}: unexpected statuses: "
            f"{unexpected_statuses}"
        )


def ingest(
    source_path: Path,
    output_dir: Path,
    chunk_size: int,
    max_chunks: int | None,
    overwrite: bool,
) -> None:

    # ---------------------------------------------------------
    # 1. Validate source file
    # ---------------------------------------------------------

    if not source_path.exists():
        raise FileNotFoundError(
            f"Source file not found: {source_path}"
        )

    if source_path.stat().st_size == 0:
        raise ValueError(
            f"Source file is empty: {source_path}"
        )

    # ---------------------------------------------------------
    # 2. Calculate source checksum
    # ---------------------------------------------------------

    print("Calculating source checksum...")

    source_checksum = calculate_sha256(
        source_path
    )

    print(
        f"Source SHA-256: {source_checksum}"
    )

    manifest_path = (
        output_dir
        / "_ingestion_manifest.json"
    )

    existing_manifest = load_manifest(
        manifest_path
    )

    # ---------------------------------------------------------
    # 3. Idempotency check
    # ---------------------------------------------------------

    if (
        output_dir.exists()
        and any(output_dir.iterdir())
    ):

        if existing_manifest is not None:

            existing_checksum = (
                existing_manifest.get(
                    "source_checksum_sha256"
                )
            )

            if (
                existing_checksum
                == source_checksum
                and not overwrite
            ):
                print()
                print("=" * 70)
                print(
                    "IDEMPOTENT INGESTION CHECK"
                )
                print("=" * 70)

                print(
                    "The exact same source file "
                    "has already been ingested."
                )

                print(
                    f"Checksum: {source_checksum}"
                )

                print(
                    "No new snapshot will be created."
                )

                print(
                    "INGESTION STATUS: SKIPPED"
                )

                print("=" * 70)

                return

        if not overwrite:
            raise FileExistsError(
                f"{output_dir} already contains data, "
                "but the source does not match the "
                "existing ingestion manifest. "
                "Use --overwrite only if you intend "
                "to rebuild the snapshot."
            )

        shutil.rmtree(
            output_dir
        )

    # Important:
    # this must be OUTSIDE the previous if block.
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ---------------------------------------------------------
    # 4. Start ingestion
    # ---------------------------------------------------------

    run_id = str(
        uuid.uuid4()
    )

    started_at = datetime.now(
        timezone.utc
    )

    total_rows = 0
    chunks_written = 0

    status_counts: dict[str, int] = {}

    print()
    print("Starting ingestion")
    print(f"Source: {source_path}")
    print(f"Output: {output_dir}")
    print(
        f"Chunk size: {chunk_size:,}"
    )
    print()

    reader = pd.read_csv(
        source_path,
        header=None,
        names=COLUMNS,
        dtype=DTYPES,
        chunksize=chunk_size,
    )

    # ---------------------------------------------------------
    # 5. Process chunks
    # ---------------------------------------------------------

    for chunk_number, chunk in enumerate(
        reader,
        start=1,
    ):

        if (
            max_chunks is not None
            and chunk_number > max_chunks
        ):
            break

        validate_chunk(
            chunk,
            chunk_number,
        )

        row_count = len(chunk)

        total_rows += row_count
        chunks_written += 1

        current_counts = (
            chunk["status"]
            .value_counts()
        )

        for status, count in current_counts.items():
            status_counts[str(status)] = (
                status_counts.get(
                    str(status),
                    0,
                )
                + int(count)
            )

        chunk["ingestion_run_id"] = (
            run_id
        )

        chunk["ingested_at_utc"] = (
            started_at
        )

        output_file = (
            output_dir
            / f"part-{chunk_number:05d}.parquet"
        )

        chunk.to_parquet(
            output_file,
            index=False,
            engine="pyarrow",
            compression="snappy",
        )

        print(
            f"Chunk {chunk_number:03d} | "
            f"rows={row_count:,} | "
            f"total={total_rows:,}"
        )

    # ---------------------------------------------------------
    # 6. Create ingestion manifest
    # ---------------------------------------------------------

    finished_at = datetime.now(
        timezone.utc
    )

    manifest = {
        "manifest_version": 1,
        "schema_version": "batch_task_v1",

        "source": {
            "file_name":
                source_path.name,

            "file_size_bytes":
                source_path.stat().st_size,
        },

        "source_checksum_algorithm":
            "sha256",

        "source_checksum_sha256":
            source_checksum,

        "ingestion": {
            "ingestion_run_id":
                run_id,

            "started_at_utc":
                started_at.isoformat(),

            "finished_at_utc":
                finished_at.isoformat(),

            "chunk_size":
                chunk_size,

            "chunks_written":
                chunks_written,

            "total_rows":
                total_rows,
        },

        "schema": {
            "columns":
                COLUMNS,

            "allowed_statuses":
                sorted(
                    ALLOWED_STATUSES
                ),
        },

        "status_counts":
            status_counts,
    }

    manifest_path = (
        output_dir
        / "_ingestion_manifest.json"
    )

    with manifest_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            manifest,
            file,
            indent=2,
        )

    # ---------------------------------------------------------
    # 7. Final output
    # ---------------------------------------------------------

    print()
    print(
        "Ingestion completed successfully."
    )

    print(
        f"Total rows: {total_rows:,}"
    )

    print(
        f"Chunks written: {chunks_written}"
    )

    print(
        f"Manifest: {manifest_path}"
    )


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )

    parser.add_argument(
        "--chunk-size",
        type=int,
        default=250_000,
    )

    parser.add_argument(
        "--max-chunks",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
    )

    return parser.parse_args()


if __name__ == "__main__":

    args = parse_args()

    ingest(
        source_path=args.source,
        output_dir=args.output,
        chunk_size=args.chunk_size,
        max_chunks=args.max_chunks,
        overwrite=args.overwrite,
    )