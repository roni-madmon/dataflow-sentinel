{{ config(
    materialized='table',
    schema='ml',
    pre_hook="SET LOCAL max_parallel_workers_per_gather = 0"
) }}

-- Experimental V2:
-- Pre-run availability of instance counts and task types is unverified in the source data.

with task_metadata as (

    select
        job_run_id,

        case
            when count(instance_num) < count(*)
                then 1
            else 0
        end as missing_instance_num_flag,

        case
            when count(task_type) = 0
                then 'missing'

            when count(task_type) < count(*)
                then 'partially_missing'

            when count(distinct task_type) = 1
                then 'type_' || min(task_type)::text

            else 'mixed'
        end as task_type_group

    from {{ ref('stg_batch_tasks') }}

    group by job_run_id

)

select
    f.*,

    g.total_instances,
    m.missing_instance_num_flag,
    m.task_type_group

from {{ ref('ml_job_features') }} as f

join {{ ref('fact_job_runs') }} as g
    on f.job_run_id = g.job_run_id

join task_metadata as m
    on f.job_run_id = m.job_run_id