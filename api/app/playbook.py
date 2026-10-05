"""Input-based checks; these are not feature attributions or root causes."""

from .schemas import JobFeatures

EXPLANATION_NOTE = (
    "The score is uncalibrated. Feature attributions are not available. "
    "Recommended checks use supplied metadata and the alert decision; "
    "they are not proven failure causes."
)


def recommended_checks(features: JobFeatures, alert: bool) -> list[str]:
    checks = []
    if features.missing_plan_cpu_flag:
        checks.append("Verify missing planned CPU values against the task plan.")
    if features.missing_plan_mem_flag:
        checks.append("Verify missing planned memory values against the task plan.")
    if features.missing_instance_num_flag:
        checks.append("Confirm the planned instance counts; supplied totals may be incomplete.")
    if features.task_type_group in {"missing", "partially_missing"}:
        checks.append("Complete the planned task-type metadata before reviewing the score.")
    if alert:
        checks.append("Manually review the planned tasks and resource requests before execution.")
    return checks
