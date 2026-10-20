"""Run from the project root: python -m streamlit run dashboard/app.py."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dashboard.client import ApiError, call_api
from dashboard.rag_page import show_rag_page
from dashboard.data import CAPACITY_POLICIES, FEATURES, load_cohorts, load_report, optional_number, parse_jobs_csv, simulate

PAGES = ["Overview", "Score jobs", "Alert queue", "Model performance", "Business simulator", "Data quality", "Knowledge assistant"]
HISTORY_LIMIT = 1000


def ratio(value, digits=1):
    return "—" if value is None or pd.isna(value) else f"{100 * value:.{digits}f}%"


def remember(jobs, predictions, source):
    if len(jobs) != len(predictions):
        raise ApiError("The API returned an unexpected number of predictions.")
    now = datetime.now(timezone.utc).isoformat()
    records = []
    for job, prediction in zip(jobs, predictions, strict=True):
        if prediction.get("job_run_id") != job["job_run_id"]:
            raise ApiError("The API response order does not match the requested job IDs.")
        records.append({**prediction, "_features": job["features"], "_source": source, "_scored_at": now})
    st.session_state.history = (st.session_state.history + records)[-HISTORY_LIMIT:]
    st.session_state.last_result = records[-1]


def history_frame(history):
    return pd.DataFrame([{
        "job_run_id": r["job_run_id"], "alert": r["alert"],
        "risk_score": r["risk_score"], "threshold": r["alert_threshold"],
        "source": r["_source"], "scored_at_utc": r["_scored_at"],
        "model_version": r["model_version"], "request_id": r["request_id"],
    } for r in history])


def show_prediction(record):
    st.subheader(f"Job · {record['job_run_id']}")
    st.caption(f"{record['_source']} · submitted {record['_scored_at']}")
    left, middle, right = st.columns(3)
    left.metric("Risk score", f"{record['risk_score']:.8f}")
    middle.metric("Frozen threshold", f"{record['alert_threshold']:.8f}")
    right.metric("Decision", "Review" if record["alert"] else "Below threshold")
    st.caption("Display values are rounded. The API compares the original values using score ≥ threshold.")
    if record["alert"]:
        st.warning("This job meets or exceeds the review threshold.")
    else:
        st.info("This job is below the review threshold. Failures may still occur.")

    # ------------------------------------------------------
    # Local SHAP explanation
    # ------------------------------------------------------

    factors = record.get(
        "main_risk_factors",
        [],
    )

    if (
        record.get("explanation_status") == "shap_local"
        and factors
    ):
        st.write("**Local model explanation**")

        explanation_rows = []

        for factor in factors:
            direction = factor.get(
                "direction"
            )

            if direction == "higher_score":
                effect = "Higher score"
            elif direction == "lower_score":
                effect = "Lower score"
            else:
                effect = "Neutral"

            explanation_rows.append(
                {
                    "Feature": factor.get(
                        "feature"
                    ),
                    "Value": str(
                        factor.get(
                            "value"
                        )
                    ),
                    "SHAP contribution": factor.get(
                        "shap_value"
                    ),
                    "Effect": effect,
                }
            )

        explanation_frame = pd.DataFrame(
            explanation_rows
        )

        st.dataframe(
            explanation_frame,
            hide_index=True,
            width="stretch",
        )

        st.caption(
            "SHAP values show how each feature moved this "
            "model score relative to the Train-only reference "
            "background. They are model attributions, not "
            "proven causes of failure."
        )

    st.write("**Suggested checks**")
    checks = record.get("recommended_checks", [])
    if checks:
        for check in checks:
            st.write(f"• {check}")
    else:
        st.caption("No checks were suggested by the current metadata playbook.")
    st.caption("The score is uncalibrated. Suggested checks are not model attributions or established failure causes.")
    with st.expander("Submitted features and complete response"):
        st.json({"features": record["_features"], "response": {k: v for k, v in record.items() if not k.startswith("_")}})


def need_report(report, report_error):
    if report is None:
        st.info("Select the saved model folder in the sidebar to load evaluation results.")
        if report_error:
            st.error(report_error)
        st.caption("Required: metadata.json and validation_test_metrics.csv from the same experiment.")
        return False
    return True


def overview(info, report, report_error):
    st.title("A clearer view of job risk")
    st.write("Review planned jobs, inspect model performance, and explore the cost of acting on alerts.")
    st.caption("EXPERIMENTAL · Scores are uncalibrated · Pre-run feature availability is unverified")
    if report is not None:
        metrics = report["metrics"]
        split = "Test" if "Test" in set(metrics["split"]) else metrics.iloc[0]["split"]
        row = metrics.loc[metrics["split"] == split].iloc[0]
        st.subheader(f"{split} evaluation")
        cells = st.columns(4)
        cells[0].metric("Evaluated jobs", f"{row['jobs']:,}")
        cells[1].metric("Alert precision", ratio(row["precision"]))
        cells[2].metric("Failure recall", ratio(row["recall"]))
        cells[3].metric("False alerts", f"{row['false_alerts']:,}")
        st.caption(f"Saved evaluation · {row['alerts']:,} alerts · {row['missed_failures']:,} missed failures · frozen threshold")
    else:
        need_report(report, report_error)
    st.divider()
    st.subheader("This session")
    history = st.session_state.history
    cells = st.columns(3)
    cells[0].metric("Predictions submitted", len(history))
    cells[1].metric("Review decisions", sum(r["alert"] for r in history))
    cells[2].metric("API", "Connected" if info else "Unavailable")
    if history:
        st.dataframe(history_frame(history[-10:]).iloc[::-1], hide_index=True, width="stretch")
    else:
        st.info("Open Score jobs to send your first request. The form includes a clearly labeled synthetic example.")
    st.caption("Session predictions are separate from the saved evaluation. This is not a live scheduler feed.")


def score_jobs(info, api_url):
    st.title("Score planned jobs")
    st.write("Send planned resource and task metadata to the running model.")
    if info is None:
        st.warning("Start or reconnect the API to enable scoring.")
    mode = st.radio("Input method", ["Single job", "CSV batch"], horizontal=True, key="input_method")
    if mode == "Single job":
        st.caption("The prefilled values are a synthetic example. Replace them with the features of a planned job when available.")
        with st.form("single_job"):
            a, b = st.columns(2)
            with a:
                job_id = st.text_input("Job run ID", "demo-job-001")
                tasks = st.number_input("Task count", min_value=1, value=1, step=1)
                instances = st.text_input("Total planned instances", "1", help="Leave blank if all instance counts are missing.")
            with b:
                task_type = st.text_input("Task type group", "type_10", help="Examples: type_1, type_10, mixed, missing, partially_missing.")
                source = st.selectbox("Input source", ["Synthetic demo", "User-provided job"])
                missing_instances = st.checkbox("Some instance counts are missing")
            cpu, mem = st.columns(2)
            raw = {}
            with cpu:
                st.markdown("**Planned CPU**")
                for prefix in ("mean", "max", "total"):
                    raw[f"{prefix}_task_plan_cpu"] = st.text_input(f"{prefix.title()} CPU", "100", key=f"cpu_{prefix}")
                missing_cpu = st.checkbox("Some CPU plans are missing")
            with mem:
                st.markdown("**Planned memory**")
                for prefix in ("mean", "max", "total"):
                    raw[f"{prefix}_task_plan_mem"] = st.text_input(f"{prefix.title()} memory", "0.1", key=f"mem_{prefix}")
                missing_mem = st.checkbox("Some memory plans are missing")
            st.caption("Use the same resource units as training. Leave unknown aggregates blank; their missing flags will be set.")
            submitted = st.form_submit_button("Score job", type="primary", disabled=info is None)
        if submitted:
            try:
                values = {k: optional_number(v) for k, v in raw.items()}
                total_instances = optional_number(instances)
                features = {"task_count": tasks, **values,
                            "total_instances": total_instances, "task_type_group": task_type.strip(),
                            "missing_plan_cpu_flag": int(missing_cpu or any(values[f"{p}_task_plan_cpu"] is None for p in ("mean", "max", "total"))),
                            "missing_plan_mem_flag": int(missing_mem or any(values[f"{p}_task_plan_mem"] is None for p in ("mean", "max", "total"))),
                            "missing_instance_num_flag": int(missing_instances or total_instances is None)}
                job = {"job_run_id": job_id.strip(), "features": features}
                with st.spinner("Scoring job…"):
                    result = call_api(api_url, "/predict", {**job, "expected_model_version": info["model_version"]})
                remember([job], [result], source)
                st.success("Prediction received and added to this session.")
            except (ValueError, ApiError) as exc:
                st.error(str(exc))
        if "last_result" in st.session_state:
            st.divider()
            st.caption("Last submitted result; editing the form does not update this result until you submit again.")
            show_prediction(st.session_state.last_result)
    else:
        template = (ROOT / "examples" / "dashboard_jobs_template.csv").read_bytes()
        st.download_button("Download synthetic CSV template", template, "dashboard_jobs_template.csv", "text/csv")
        uploaded = st.file_uploader("Jobs CSV · up to 500 rows / 5 MB", type="csv")
        source = st.selectbox("Batch source", ["Synthetic demo", "User-provided jobs"], key="batch_source")
        st.caption("Required columns: job_run_id and all 12 features. Do not include labels, timestamps, or outcome fields.")
        jobs = None
        if uploaded:
            try:
                jobs = parse_jobs_csv(uploaded.getvalue(), max_rows=min(500, info["max_batch_size"]) if info else 500)
                st.dataframe(pd.DataFrame([{"job_run_id": j["job_run_id"], **j["features"]} for j in jobs]), hide_index=True, width="stretch")
            except ValueError as exc:
                st.error(str(exc))
        if st.button("Score batch", type="primary", disabled=info is None or jobs is None):
            try:
                with st.spinner("Scoring batch…"):
                    result = call_api(api_url, "/predict/batch", {"jobs": jobs, "expected_model_version": info["model_version"]})
                remember(jobs, result["predictions"], source)
                st.success(f"Scored {result['total']} jobs; {result['alerts']} review decisions. Open Alert queue for details.")
            except ApiError as exc:
                st.error(str(exc))


def alert_queue():
    st.title("Alert queue")
    st.caption(f"Current browser session only · latest {HISTORY_LIMIT:,} prediction records · no outcome labels")
    history = st.session_state.history
    if not history:
        st.info("Submit jobs on the Score jobs page to populate this queue.")
        return
    filter_value = st.radio("Show", ["Alerts", "All predictions", "Below threshold"], horizontal=True)
    source_filter = st.selectbox("Source", ["All sources"] + sorted({r["_source"] for r in history}))
    selected = [r for r in history if (filter_value == "All predictions" or r["alert"] == (filter_value == "Alerts"))
                and (source_filter == "All sources" or r["_source"] == source_filter)]
    selected = sorted(selected, key=lambda r: r["risk_score"], reverse=True)
    if selected:
        frame = history_frame(selected)
        st.dataframe(frame, hide_index=True, width="stretch")
        st.download_button("Download displayed predictions", frame.to_csv(index=False).encode("utf-8-sig"), "session_predictions.csv", "text/csv")
        index = st.selectbox("Inspect prediction", range(len(selected)), format_func=lambda i: f"{selected[i]['job_run_id']} · {selected[i]['request_id'][:8]}")
        show_prediction(selected[index])
    else:
        st.info("No predictions match these filters.")
    if st.button("Clear session predictions"):
        st.session_state.history = []
        st.session_state.pop("last_result", None)
        st.rerun()


def performance(report, report_error):
    st.title("Model performance")
    if not need_report(report, report_error):
        return
    metrics = report["metrics"]
    st.caption(f"Saved artifact: {report['model_version']}")
    columns = ["split", "jobs", "failure_pct", "ap", "precision", "recall", "f1", "alerts", "false_alerts", "missed_failures", "alert_pct"]
    st.dataframe(metrics[columns], hide_index=True, width="stretch")
    st.caption("Precision, recall and F1 are recomputed from saved counts. AP is read from the saved ranking evaluation; percentages are labeled _pct.")
    st.bar_chart(metrics.set_index("split")[["ap", "precision", "recall", "f1"]], stack=False, y_label="Metric value", height=300)
    split = st.selectbox("Inspect evaluation split", metrics["split"].tolist(), index=len(metrics)-1)
    row = metrics.loc[metrics["split"] == split].iloc[0]
    left, right = st.columns(2)
    with left:
        st.subheader("Confusion matrix")
        st.dataframe(pd.DataFrame([[row["true_negatives"], row["false_alerts"]], [row["missed_failures"], row["true_alerts"]]],
                                 index=["Actual success", "Actual failure"], columns=["No alert", "Alert"]), width="stretch")
    with right:
        st.subheader("Ranking context")
        st.metric("Failure prevalence / constant-score AP", ratio(row["failure_pct"] / 100, 3))
        st.metric("Observed alert rate", f"{row['alert_pct']:.2f}%")
        st.caption("Changes in the population and failure prevalence affect how results transfer between periods.")
    st.info("The threshold was selected on Validation and frozen before Test. This dashboard does not optimize it on Test.")
    st.subheader("Saved cohort analysis")
    by_instances = st.checkbox("Break down by instance group")
    try:
        cohorts = load_cohorts(report["directory"], by_instances)
        if "split" in cohorts:
            cohorts = cohorts[cohorts["split"].astype(str).str.lower() == split.lower()]
        st.dataframe(cohorts, hide_index=True, width="stretch")
    except FileNotFoundError:
        st.caption("This cohort report is not present in the selected artifact folder.")
    except (ValueError, OSError) as exc:
        st.warning(f"Could not read the cohort report: {exc}")
    with st.expander("Evaluation assumptions and limitations"):
        st.json(report["metadata"].get("limitations", []))
        st.write("Test results have already been inspected. Changes informed by them require a separately held-out future evaluation.")


def business(report, report_error):
    st.title("Business simulator")
    st.write(
        "Compare the frozen Validation review-capacity policies under explicit "
        "cost and prevention assumptions."
    )

    if not need_report(report, report_error):
        return

    st.caption(
        "Policy selection uses Validation only. Test was not used to choose "
        "the operating policy."
    )

    comparison_rows = []

    for name, policy in CAPACITY_POLICIES.items():
        precision = (
            policy["tp"] / policy["alerts"]
            if policy["alerts"]
            else 0.0
        )

        failures = policy["tp"] + policy["fn"]

        recall = (
            policy["tp"] / failures
            if failures
            else 0.0
        )

        comparison_rows.append(
            {
                "Policy": name,
                "Capacity": f"{policy['capacity_pct']:.2f}%",
                "Alerts": policy["alerts"],
                "Precision": precision,
                "Recall": recall,
                "Missed failures": policy["fn"],
            }
        )

    comparison = pd.DataFrame(comparison_rows)

    st.subheader("Operating-policy comparison")

    display_comparison = comparison.copy()

    display_comparison["Precision"] = (
        display_comparison["Precision"]
        .map(lambda value: f"{100 * value:.2f}%")
    )

    display_comparison["Recall"] = (
        display_comparison["Recall"]
        .map(lambda value: f"{100 * value:.2f}%")
    )

    st.dataframe(
        display_comparison,
        hide_index=True,
        width="stretch",
    )

    policy_name = st.selectbox(
        "Operating policy",
        list(CAPACITY_POLICIES),
        index=1,
    )

    policy = CAPACITY_POLICIES[policy_name]

    counts = {
        "jobs": policy["jobs"],
        "alerts": policy["alerts"],
        "tp": policy["tp"],
        "fp": policy["fp"],
        "fn": policy["fn"],
    }

    failures = policy["tp"] + policy["fn"]

    precision = (
        policy["tp"] / policy["alerts"]
        if policy["alerts"]
        else 0.0
    )

    recall = (
        policy["tp"] / failures
        if failures
        else 0.0
    )

    a, b, c, d = st.columns(4)

    a.metric(
        "Review capacity",
        f"{policy['capacity_pct']:.2f}%",
    )

    b.metric(
        "Alerts",
        f"{policy['alerts']:,}",
    )

    c.metric(
        "Precision",
        f"{100 * precision:.2f}%",
    )

    d.metric(
        "Failure recall",
        f"{100 * recall:.2f}%",
    )

    st.caption(
        f"Validation population ? {policy['jobs']:,} jobs ? "
        f"{policy['tp']:,} correctly flagged failures ? "
        f"{policy['fp']:,} false alerts ? "
        f"{policy['fn']:,} missed failures"
    )

    if policy_name == "Balanced 7.36% (Recommended)":
        st.success(
            "Balanced 7.36% is the default development policy. "
            "It represents the Validation capacity elbow under the "
            "current analysis; it is not claimed to be production-optimal."
        )

    st.caption(
        "Exact capacity uses score descending with deterministic "
        "md5(job_run_id) ordering inside score ties. The tie-break does "
        "not imply a model-risk difference between tied Jobs."
    )

    a, b, c = st.columns(3)

    with a:
        failure_cost = st.number_input(
            "Assumed cost per failure",
            min_value=0.0,
            value=100.0,
            step=10.0,
        )

    with b:
        review_cost = st.number_input(
            "Assumed cost per reviewed alert",
            min_value=0.0,
            value=10.0,
            step=1.0,
        )

    with c:
        unit = st.selectbox(
            "Currency / unit",
            ["Cost units", "ILS", "USD"],
        )

    st.caption(
        "All cost and prevention inputs below are illustrative assumptions, "
        "not estimates learned from this dataset."
    )

    a, b, c = st.columns(3)

    with a:
        conservative = st.slider(
            "Conservative prevention (%)",
            0,
            100,
            10,
        )

    with b:
        base = st.slider(
            "Base prevention (%)",
            0,
            100,
            25,
        )

    with c:
        optimistic = st.slider(
            "Optimistic prevention (%)",
            0,
            100,
            50,
        )

    if not conservative <= base <= optimistic:
        st.error(
            "Set prevention assumptions in increasing order: "
            "conservative ? base ? optimistic."
        )
        return

    scenarios = []

    for name, rate in [
        ("Conservative", conservative),
        ("Base", base),
        ("Optimistic", optimistic),
    ]:
        result = simulate(
            **counts,
            failure_cost=failure_cost,
            review_cost=review_cost,
            prevention_rate=rate / 100,
        )

        scenarios.append(
            {
                "scenario": name,
                "prevention_pct": rate,
                **result,
            }
        )

    result = scenarios[1]

    a, b, c = st.columns(3)

    a.metric(
        f"Base net benefit ? {unit}",
        f"{result['net_benefit']:,.2f}",
    )

    b.metric(
        f"Base net / 1,000 jobs ? {unit}",
        f"{result['net_per_1000_jobs']:,.2f}",
    )

    c.metric(
        "Assumed prevented failures",
        f"{result['prevented_failures']:,.1f}",
    )

    if result["net_benefit"] < 0:
        st.warning(
            "Under the base assumptions, review costs exceed "
            "the modeled benefit."
        )

    st.dataframe(
        pd.DataFrame(scenarios),
        hide_index=True,
        width="stretch",
    )

    break_even = result["break_even_prevention"]

    if break_even is None:
        st.caption(
            "A break-even prevention rate is undefined because "
            "detected-failure value is zero."
        )

    elif break_even > 1:
        st.caption(
            f"Break-even would require "
            f"{100 * break_even:.1f}% prevention, which is not "
            "feasible under these cost assumptions."
        )

    else:
        st.caption(
            "Break-even prevention rate among correctly flagged "
            f"failures: {100 * break_even:.1f}%."
        )

    curve = pd.DataFrame(
        [
            {
                "prevention_pct": p,
                "Net benefit": simulate(
                    **counts,
                    failure_cost=failure_cost,
                    review_cost=review_cost,
                    prevention_rate=p / 100,
                )["net_per_1000_jobs"],
                "Break even": 0.0,
            }
            for p in range(101)
        ]
    )

    st.line_chart(
        curve.set_index("prevention_pct"),
        x_label="Assumed prevention (%)",
        y_label=f"Net per 1,000 jobs ? {unit}",
        height=300,
    )

    st.caption(
        "Every alert incurs review cost. Only correctly flagged failures "
        "can be prevented in this simulation. Comparison baseline: no "
        "alert-review program; other operating costs are excluded."
    )

    with st.expander("Calculation"):
        st.code(
            "prevented = true_alerts ? assumed_prevention_rate\n"
            "gross_benefit = prevented ? assumed_failure_cost\n"
            "review_cost = alerts ? assumed_cost_per_alert\n"
            "net_benefit = gross_benefit ? review_cost"
        )

    export = (
        pd.DataFrame(scenarios)
        .assign(
            unit=unit,
            split="Validation",
            operating_policy=policy_name,
            capacity_pct=policy["capacity_pct"],
            model_version=report["model_version"],
            jobs=policy["jobs"],
            alerts=policy["alerts"],
            true_alerts=policy["tp"],
            false_alerts=policy["fp"],
            missed_failures=policy["fn"],
            assumed_failure_cost=failure_cost,
            assumed_review_cost=review_cost,
        )
    )

    st.download_button(
        "Download scenarios",
        export.to_csv(index=False).encode("utf-8-sig"),
        "business_scenarios.csv",
        "text/csv",
    )

def quality(info, report):
    st.title("Data quality & model context")
    st.write("Inspect missing metadata in submitted jobs and the evaluation population recorded with the model.")
    history = st.session_state.history
    if history:
        flags = ["missing_plan_cpu_flag", "missing_plan_mem_flag", "missing_instance_num_flag"]
        st.dataframe(pd.DataFrame([{"missing_metadata_flag": flag, "flagged_predictions": sum(bool(r["_features"][flag]) for r in history), "total_predictions": len(history)} for flag in flags]), hide_index=True, width="stretch")
        st.caption("Counts describe submitted prediction records, including any synthetic demos and repeat submissions.")
    else:
        st.info("No session inputs to inspect yet.")
    if report:
        metadata = report["metadata"]
        st.subheader("Recorded evaluation population")
        for key, title in [("rows", "Split sizes"), ("test_label_time_exclusions", "Test label-time exclusions"), ("evaluation_population", "Population definition")]:
            if key in metadata:
                st.write(f"**{title}**")
                st.json(metadata[key])
    st.info("Task types, task counts, instance counts and planned resources must be available at prediction time for a true pre-run deployment. The source data does not independently establish that availability, so it remains unverified.")
    if info:
        with st.expander("Active model and feature contract"):
            st.json(info)
    st.caption("This page does not execute dbt tests or continuously monitor the source database.")


def main():
    st.set_page_config(page_title="DataFlow Sentinel", page_icon="◈", layout="wide")
    st.markdown("""<style>
    .block-container {padding-top: 2rem; max-width: 1400px;}
    [data-testid="stMetric"] {border: 1px solid #dbe6e9; border-radius: 12px; padding: 16px;}
    </style>""", unsafe_allow_html=True)
    if "history" not in st.session_state:
        st.session_state.history = []
    with st.sidebar:
        st.title("DataFlow\nSentinel")
        st.caption("JOB RISK WORKSPACE")
        page = st.radio("Workspace", PAGES, label_visibility="collapsed", key="page")
        st.divider()
        api_url = st.text_input("API address", os.environ.get("SENTINEL_API_URL", "http://127.0.0.1:8000"))
        directory = st.text_input("Saved model folder", os.environ.get("SENTINEL_MODEL_PATH", ""))
        if st.button("Refresh connection"):
            st.rerun()
    info, connection_error = None, None
    try:
        info = call_api(api_url, "/model-info", timeout=3)
        if info.get("feature_columns") != FEATURES:
            raise ApiError("The API feature schema does not match this dashboard version.")
    except ApiError as exc:
        info, connection_error = None, str(exc)
    with st.sidebar:
        if info:
            st.success("API connected")
            st.caption(f"{info['model_name']} · {info['model_status']}")
            st.caption("Scores are not calibrated probabilities.")
        else:
            st.warning(connection_error)
    report, report_error = None, None
    if directory.strip():
        path = Path(directory.strip()).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        try:
            report = load_report(path, info["model_version"] if info else None)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            report_error = f"Could not load saved evaluation: {exc}"
    if page == "Overview":
        overview(info, report, report_error)
    elif page == "Score jobs":
        score_jobs(info, api_url)
    elif page == "Alert queue":
        alert_queue()
    elif page == "Model performance":
        performance(report, report_error)
    elif page == "Business simulator":
        business(report, report_error)
    elif page == "Knowledge assistant":
        show_rag_page(api_url)
    else:
        quality(info, report)


if __name__ == "__main__":
    main()
