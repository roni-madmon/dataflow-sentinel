FROM apache/airflow:3.3.2-python3.12

COPY pipeline-requirements.txt /tmp/pipeline-requirements.txt

RUN python -m venv /opt/airflow/pipeline-venv \
    && /opt/airflow/pipeline-venv/bin/pip install \
        --no-cache-dir \
        -r /tmp/pipeline-requirements.txt
