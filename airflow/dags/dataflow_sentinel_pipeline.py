from datetime import datetime

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator


PROJECT = "/opt/airflow/project"
PIPELINE_PYTHON = "/opt/airflow/pipeline-venv/bin/python"
DBT = "/opt/airflow/pipeline-venv/bin/dbt"


with DAG(
    dag_id="dataflow_sentinel_data_pipeline",
    description=(
        "Fail-fast DataFlow Sentinel ingestion, "
        "PostgreSQL staging, and dbt build."
    ),
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=["dataflow-sentinel", "data-engineering"],
) as dag:

    bronze_ingestion = BashOperator(
        task_id="bronze_ingestion",
        bash_command=(
            f"{PIPELINE_PYTHON} "
            f"{PROJECT}/src/ingestion/"
            "ingest_batch_tasks.py"
        ),
        cwd=PROJECT,
        retries=0,
    )

    postgres_staging_load = BashOperator(
        task_id="postgres_staging_load",
        bash_command=(
            f"{PIPELINE_PYTHON} "
            f"{PROJECT}/src/ingestion/"
            "load_bronze_to_postgres.py "
            "--replace"
        ),
        cwd=PROJECT,
        retries=0,
    )

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=(
            f"{DBT} build "
            f"--project-dir {PROJECT}/dbt/dataflow_dbt "
            f"--profiles-dir {PROJECT}/airflow "
            "--fail-fast"
        ),
        cwd=PROJECT,
        retries=0,
    )

    (
        bronze_ingestion
        >> postgres_staging_load
        >> dbt_build
    )
