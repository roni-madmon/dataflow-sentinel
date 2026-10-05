with job_runs as (

    select *
    from {{ ref('fact_job_runs') }}

)

select

    -- Identifiers / evaluation metadata
    job_run_id,

    -- Used only for chronological Train / Validation / Test split.
    -- Not a model feature.
    run_start_time as split_timestamp,

    -- Leakage-safe pre-run features
    task_count,

    mean_task_plan_cpu,
    max_task_plan_cpu,
    total_task_plan_cpu,

    mean_task_plan_mem,
    max_task_plan_mem,
    total_task_plan_mem,

    case
        when missing_plan_cpu_tasks > 0 then 1
        else 0
    end as missing_plan_cpu_flag,

    case
        when missing_plan_mem_tasks > 0 then 1
        else 0
    end as missing_plan_mem_flag,

    -- Target only
    failed_job

from job_runs
