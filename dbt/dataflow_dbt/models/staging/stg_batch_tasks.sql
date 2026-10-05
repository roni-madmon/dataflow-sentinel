with source as (

    select *
    from {{ source('dataflow_source', 'batch_tasks_source') }}

),

cleaned as (

    select

        job_name::text as job_run_id,

        task_name::text as task_name,

        md5(
            job_name::text
            || '|'
            || task_name::text
        ) as task_key,

        instance_num::bigint as instance_num,

        task_type::bigint as task_type,

        lower(trim(status)) as task_status,

        start_time::bigint as start_time,

        end_time::bigint as end_time,

        plan_cpu::double precision as plan_cpu,

        plan_mem::double precision as plan_mem,

        ingestion_run_id,

        ingested_at_utc

    from source

)

select *
from cleaned