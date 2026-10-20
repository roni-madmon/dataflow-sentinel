-- NULL label times are allowed when timing evidence is insufficient.
-- Every gold job must have exactly one row, enforced with the key tests.

with checked as (

    select
        coalesce(g.job_run_id, l.job_run_id) as job_run_id,
        g.run_start_time,
        l.label_available_time,

        case
            when g.job_run_id is null
                then 'unknown_job'

            when l.job_run_id is null
                then 'missing_label_row'

            when l.label_available_time is not null
                 and (
                     l.label_available_time <= 0
                     or g.run_start_time is null
                     or l.label_available_time < g.run_start_time
                 )
                then 'invalid_label_time'
        end as failure_reason

    from {{ ref('fact_job_runs') }} as g

    full outer join {{ ref('ml_job_label_times') }} as l
        on g.job_run_id = l.job_run_id

)

select *
from checked
where failure_reason is not null
