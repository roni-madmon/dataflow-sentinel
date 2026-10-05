{{ config(materialized='table', schema='ml') }}

with task_times as (

    select
        job_run_id,

        min(end_time) filter (
            where task_status = 'failed'
              and start_time > 0
              and end_time >= start_time
        ) as failed_at,

        max(end_time) filter (
            where task_status = 'terminated'
        ) as succeeded_at,

        count(*) filter (
            where task_status = 'terminated'
              and (
                  start_time is null
                  or end_time is null
                  or start_time <= 0
                  or end_time < start_time
              )
        ) as bad_success_times

    from {{ ref('stg_batch_tasks') }}
    where task_status in ('failed', 'terminated')
    group by job_run_id

)

select
    g.job_run_id,

    case
        when g.failed_job = 1
             and t.failed_at >= g.run_start_time
            then t.failed_at

        when g.failed_job = 0
             and t.bad_success_times = 0
             and t.succeeded_at >= g.run_start_time
            then t.succeeded_at

        else null
    end as label_available_time

from {{ ref('fact_job_runs') }} as g
left join task_times as t
    on g.job_run_id = t.job_run_id