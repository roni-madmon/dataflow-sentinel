with task_level as (

    select *
    from {{ ref('stg_batch_tasks') }}

),

job_aggregates as (

    select

        job_run_id,

        count(*) as task_count,

        count(*) filter (
            where task_status = 'failed'
        ) as failed_task_count,

        count(*) filter (
            where task_status = 'terminated'
        ) as terminated_task_count,

        count(*) filter (
            where task_status = 'running'
        ) as running_task_count,

        count(*) filter (
            where task_status = 'waiting'
        ) as waiting_task_count,

        -- Ignore zero start times on waiting tasks when calculating job start.
        min(
            case
                when task_status = 'waiting' and start_time = 0
                    then null
                else start_time
            end
        ) as run_start_time,

        max(end_time) as run_end_time,

        sum(instance_num) as total_instances,

        avg(plan_cpu) as mean_task_plan_cpu,

        max(plan_cpu) as max_task_plan_cpu,

        sum(plan_cpu) as total_task_plan_cpu,

        avg(plan_mem) as mean_task_plan_mem,

        max(plan_mem) as max_task_plan_mem,

        sum(plan_mem) as total_task_plan_mem,

        count(*) filter (
            where plan_cpu is null
        ) as missing_plan_cpu_tasks,

        count(*) filter (
            where plan_mem is null
        ) as missing_plan_mem_tasks

    from task_level

    group by job_run_id

),

labeled_jobs as (

    select

        *,

        case
            when failed_task_count > 0
                then 1

            when failed_task_count = 0
                 and running_task_count = 0
                 and waiting_task_count = 0
                 and terminated_task_count = task_count
                then 0

            else null
        end as failed_job

    from job_aggregates

)

select *
from labeled_jobs

where failed_job is not null