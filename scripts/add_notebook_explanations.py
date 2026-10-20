import copy
import csv
import json
from datetime import datetime
from html import escape
from pathlib import Path
from shutil import copy2

root = Path.cwd()
path = root / "notebooks/02_hgb_v2_training.ipynb"
audit_path = root / "docs/implementation_alignment_v3.md"
model_dir = root / "artifacts/models/hgb_v2_20261002T104801_398392Z"

notebook = json.loads(path.read_text(encoding="utf-8-sig"))
before = copy.deepcopy(notebook)

notes = {
    "hgb-v2-introduction": (
        "DataFlow Sentinel | הסבר הפרויקט",
        "מטרת הפרויקט היא לעזור לצוות Data/Operations לתעדף אילו ג'ובים לבדוק לפני הרצה. בניתי מערכת ניסיונית המחברת עיבוד נתונים, מודל סיכון, API, דשבורד ועוזר ידע מקומי. במאגר שהכנו יש 14,295,731 רשומות Task ו-4,161,396 שורות Job run עם יעד ידוע. השימוש לפני הרצה מותנה בכך שכל הפיצ'רים אכן זמינים אז; הנחה זו עדיין דורשת אימות. הפלטים השמורים במחברת הם מהריצה המקורית. הגרסה המסודרת טרם הורצה מחדש מתחילתה ועד סופה.",
        "DataFlow Sentinel is an experimental system for prioritizing job reviews. It combines data engineering, risk modeling, an API, a dashboard, and a local knowledge assistant. The prepared dataset contains 14,295,731 task records and 4,161,396 job-run rows with known targets. Pre-run use depends on verifying feature availability at prediction time. Retained outputs come from the original run; the curated notebook has not been rerun end-to-end.",
    ),
    "hgb-v2-section-0": (
        "Environment | סביבת העבודה",
        "אני מאתרת את תיקיית הפרויקט ובודקת שגרסאות ספריות ה-ML תואמות ל-metadata של המודל השמור. כך ניתן לזהות הבדלי סביבה לפני האימון. requirements-model.txt מתעד חמש ספריות מרכזיות; הוא עדיין אינו נעילה מלאה של סביבת הפרויקט.",
        "Locate the project and check the core ML package versions against the saved model metadata. This detects environment differences before training. requirements-model.txt pins five core packages, but does not lock the complete project environment.",
    ),
    "hgb-v2-section-3": (
        "Data model and target | מבנה הנתונים והיעד",
        "המודל פועל ברמת Job run, כי זו יחידת ההחלטה התפעולית. SQL מרכז את המשימות לפי job_run_id. היעד הוא 1 אם לפחות Task אחד נכשל, ו-0 כאשר כל המשימות הסתיימו בהצלחה לפי מיפוי הסטטוסים. מקרים ללא יעד ידוע אינם נכללים. בדיקת ייחודיות המפתח חשובה, אך אינה לבדה הוכחה לכך ש-job_name אינו מערבב הרצות שונות.",
        "The prediction unit is a job run, matching the operational decision. SQL aggregates tasks by job_run_id. The target is 1 if any task failed, and 0 if all tasks completed successfully under the status mapping. Unresolved targets are excluded. Key uniqueness is necessary, but does not alone prove that job_name separates different executions.",
    ),
    "hgb-v2-section-4": (
        "Data quality | איכות הנתונים",
        "אני בודקת ערכים חסרים, תקינות יעד וחותמות זמן. זמני התחלה אפסיים אינם משמשים לחלוקה הכרונולוגית. מזהי ג'ובים, סטטוסים סופיים וזמני סיום אינם פיצ'רים של המודל; חלקם משמשים לבניית היעד ולבדיקת זמינותו. הפרדה זו מצמצמת דליפה גלויה, אך אינה מוכיחה שכל מטאדאטת הקלט ידועה לפני ההרצה.",
        "Audit missing values, targets, and timestamps. Zero start times are excluded from chronological splitting. Job IDs, final statuses, and end times are not model inputs; some support target construction and label-time checks. Removing outcome fields does not by itself establish that all remaining metadata is available before execution.",
    ),
    "hgb-v2-section-9": (
        "Temporal evaluation | חלוקה בזמן וזמינות תוויות",
        "חילקתי לפי זמן התחלת הריצה, עם גבולות המבוססים על אחוזונים 70 ו-85. הגבולות השמורים הם 520423 ו-608501. ב-Train וב-Validation נכללים רק ג'ובים שתוצאתם הייתה ידועה עד סוף התקופה המתאימה. כך האימון אינו משתמש בתוויות שהתבררו רק בעתיד. זמן ההתחלה הוא אמצעי לחלוקת הניסוי, ולא פיצ'ר או הוכחה לזמן התרעה אמיתי.",
        "Use chronological boundaries at the 70th and 85th percentiles: 520423 and 608501 in the recorded run. Train and Validation include only labels available by their respective cutoffs. This avoids learning from outcomes that were not yet known. Actual start time orders the experiment; it is neither a model feature nor an observed pre-run alert timestamp.",
    ),
    "hgb-v2-section-12": (
        "Model inputs | נתוני האימון והפיצ'רים",
        "לאחר הסינון התקבלו 2,912,014 ג'ובים ב-Train ו-623,763 ב-Validation. גרסה V1 כוללת תשעה פיצ'רים: מספר משימות, ממוצע/מקסימום/סכום של תכנון CPU וזיכרון, ושני דגלי חוסר. הסכומים הם סכומי תכנון ברמת Task, ולא צריכת משאבים בפועל. טעינה במנות מקלה על הקריאה, אך טבלאות האימון המלאות עדיין מוחזקות בזיכרון.",
        "After filtering, Train contains 2,912,014 jobs and Validation contains 623,763. V1 has nine features: task count, mean/max/sum of planned CPU and memory, and two missingness flags. Resource sums aggregate task plans, not measured runtime consumption. Chunked reads simplify loading, but the complete training tables still reside in memory.",
    ),
    "hgb-v2-section-16": (
        "Baselines | מודלי ייחוס",
        "אני משווה למודל שנותן ציון קבוע ול-Logistic Regression. השלמת ערכים חסרים והסקיילינג מותאמים על Train בלבד באמצעות Pipeline. משקולות המחלקות נותנות משקל גדול יותר לכשלים הנדירים. Accuracy אינו המדד הראשי; מדד הדירוג בקוד הוא Average Precision, או AP. אין להציג אותו כשטח טרפזי שחושב מתחת לעקומת PR.",
        "Compare a constant-score reference with Logistic Regression. Median imputation and scaling are fitted on Train only inside a Pipeline. Class weighting emphasizes the rare failure class. Accuracy is not the primary metric. The code reports Average Precision (AP), a precision-recall ranking summary, rather than trapezoidal PR-AUC.",
    ),
    "hgb-v2-section-20": (
        "HGB V1 and tied scores | מודל לא ליניארי וציונים זהים",
        "HistGradientBoosting מאפשר קשרים לא ליניאריים בין הפיצ'רים. ב-V1 נמצאה קבוצה גדולה עם אותו ציון. סף יחיד בוחר את כל הקבוצה או אף אחד ממנה, ולכן תקציב התראות עלול להישאר לא מנוצל. הניתוח ב-Validation הוביל לבדיקת מטאדאטה נוספת. HGB הוא המודל שנבדק בפועל; מועמד XGBoost והיוריסטיקה העסקית שבמפרט עדיין חסרים במסלול הנוכחי.",
        "HistGradientBoosting models nonlinear feature relationships. V1 assigns an identical score to a large group, so a threshold must include or exclude that entire group and may underfill an alert budget. Validation analysis motivated additional metadata. HGB is the evaluated model; the specification's XGBoost candidate and business-heuristic baseline are still missing from the current workflow.",
    ),
    "hgb-v2-section-25": (
        "HGB V2 | שיפור באמצעות מטאדאטה",
        "ב-V2 הוספתי total_instances, דגל חוסר במספר המופעים ו-task_type_group, ובסך הכול 12 פיצ'רים. סוג המשימה מקודד אך מסומן למודל כקטגוריאלי, ולכן הקודים אינם דירוג מספרי של הסוגים. ב-Validation ה-AP עלה מ-0.2907 ל-0.5169 וה-F1 מ-0.4293 ל-0.6629 לעומת HGB V1. שיפור זה אינו מוכיח שמספר המופעים וסוגי המשימות זמינים לפני הריצה; לכן V2 נשאר ניסיוני.",
        "V2 adds total_instances, its missingness flag, and task_type_group, for 12 inputs. Task-type codes are explicitly treated as categorical, not as ordered numeric magnitudes. Validation AP improves from 0.2907 to 0.5169 and F1 from 0.4293 to 0.6629 relative to HGB V1. Predictive improvement does not establish pre-run availability, so V2 remains experimental.",
    ),
    "hgb-v2-section-28": (
        "Threshold and Test | הקפאת הסף ובדיקת הכללה",
        "הסף 0.9696205830070223 נבחר למקסום F1 ב-Validation והוקפא לפני Test. התרעה מתקבלת כאשר score >= threshold. זהו סף השוואה ניסיוני; עדיין לא נבחרה מדיניות לפי עלויות וקיבולת צוות כנדרש במפרט. ב-Test נשארו 624,196 ג'ובים לאחר הוצאת שלוש שורות ללא זמן תווית. Precision עונה כמה מההתראות נכונות, ו-Recall עונה כמה מהכשלים זוהו. score של 0.97 אינו אומר 97% סיכוי לכשל.",
        "The threshold 0.9696205830070223 maximizes Validation F1 and was frozen before Test. Alert when score >= threshold. It is an experimental benchmark threshold, not yet a cost-and-capacity policy. Test contains 624,196 jobs after excluding three rows without label times. Precision measures correct alerts; recall measures detected failures. A score of 0.97 is not a calibrated 97% failure probability.",
    ),
    "hgb-v2-section-30": (
        "Saved artifact | שמירת המודל",
        "אני שומרת את ה-Pipeline, סדר וסוגי הפיצ'רים, הסף, גבולות החלוקה וגרסאות הספריות. השירות טוען את המודל השמור כדי לבצע חיזוי באותו תהליך עיבוד. בדיקת טעינה חוזרת משווה ציונים לפני ואחרי השמירה. הרצה חדשה נשמרת בתיקייה חדשה; היא אינה מחליפה אוטומטית את מודל הדמו.",
        "Save the Pipeline, feature order and dtypes, threshold, split boundaries, and package versions. Serving loads this artifact and reuses its preprocessing. Reload checks compare scores before and after serialization. A new notebook execution writes a new experiment directory rather than automatically replacing the demo model.",
    ),
    "hgb-v2-section-31": (
        "Error analysis | מה למדנו מהטעויות",
        "ב-Test ה-Precision ירד ל-12.35% וה-Recall ל-51.11%. נרשמו 17,378 התראות שווא ו-2,342 כשלים שלא זוהו. בקבוצת type_10 עם מופע אחד שיעור הכשל ירד מ-42.33% ב-Validation ל-5.82% ב-Test. זו עדות לשינוי בין התקופות, ולא הוכחה לסיבה יחידה לירידה. מכיוון שכבר בחנו את Test, שינוי מודל או מדיניות בעקבותיו מחייב תקופת הערכה חדשה שלא שימשה לבחירה.",
        "Test precision falls to 12.35% and recall to 51.11%, with 17,378 false alerts and 2,342 missed failures. For type_10 jobs with one instance, failure prevalence changes from 42.33% in Validation to 5.82% in Test. This documents a period shift, not a complete causal explanation. Further model or policy choices informed by Test require a new held-out evaluation period.",
    ),
    "hgb-v2-section-33": (
        "Inference parity | התאמה בין המחברת לשירות",
        "בדקנו 1,000 חיזויים מול המחברת ואימתנו התאמה בציונים, בסף ובהחלטות ההתראה. בדיקה זו תומכת בתקינות ההעברה למוצר; היא אינה מוכיחה שהמודל שימושי עסקית או מוכן לייצור. במחברת המסודרת הבדיקה מכוונת למודל שנשמר באותה הרצה.",
        "The reported 1,000-row parity check matched notebook scores, threshold, and alert decisions. This supports serving consistency, not operational utility or production readiness. The curated notebook verifies the artifact saved in the same execution.",
    ),
}


def bilingual(title, hebrew, english, level=2):
    return (
        f"{'#' * level} {title}\n\n"
        f'<div dir="rtl"><p><strong>עברית:</strong> {escape(hebrew)}</p></div>\n\n'
        f"**English:** {english}\n"
    )


for cell_id, content in notes.items():
    matches = [c for c in notebook["cells"] if c.get("id") == cell_id]
    if len(matches) != 1 or matches[0]["cell_type"] != "markdown":
        raise SystemExit(
            f"Expected Markdown cell missing: {cell_id}. No files changed."
        )
    level = 1 if cell_id == "hgb-v2-introduction" else 2
    matches[0]["source"] = bilingual(
        *content, level=level
    ).splitlines(keepends=True)


def append_note(cell_id, content):
    matches = [c for c in notebook["cells"] if c.get("id") == cell_id]
    if matches:
        if len(matches) != 1 or matches[0]["cell_type"] != "markdown":
            raise SystemExit(
                f"Unexpected existing cell: {cell_id}. No files changed."
            )
        matches[0]["source"] = content.splitlines(keepends=True)
    else:
        notebook["cells"].append({
            "cell_type": "markdown",
            "id": cell_id,
            "metadata": {},
            "source": content.splitlines(keepends=True),
        })


with (model_dir / "validation_test_metrics.csv").open(
    encoding="utf-8-sig", newline=""
) as f:
    rows = {r["split"].lower(): r for r in csv.DictReader(f)}

metric_table = (
    "| Split | Jobs | AP | Precision | Recall | F1 | False alerts | Missed failures |\n"
    "|---|---:|---:|---:|---:|---:|---:|---:|\n"
)

for split in ("validation", "test"):
    row = {key.lower(): value for key, value in rows[split].items()}
    n, alerts, fp, fn = [
        int(float(row[key]))
        for key in ("jobs", "alerts", "false_alerts", "missed_failures")
    ]
    tp = alerts - fp

    if not (0 <= fp <= alerts <= n and 0 <= fn <= n - alerts and tp > 0):
        raise SystemExit("Invalid saved evaluation counts. No files changed.")

    metric_table += (
        f"| {split.title()} | {n:,} | {float(row['ap']):.4f} | "
        f"{tp / alerts:.4f} | {tp / (tp + fn):.4f} | "
        f"{2 * tp / (2 * tp + fp + fn):.4f} | {fp:,} | {fn:,} |\n"
    )

append_note("hgb-v2-recorded-results", bilingual(
    "Recorded results | התוצאות שאציג",
    "הטבלה הבאה נקראת מהמדדים של המודל השמור hgb_v2_20261002T104801_398392Z. היא מתעדת את הריצה המקורית, ולא תוצאות של אימון חדש. ב-Test מדד AP הוא 0.1948 לעומת 0.0077 למודל שנותן ציון קבוע. שיפור בדירוג אינו מבטל את מספר התראות השווא ואת הצורך בבדיקת כדאיות תפעולית.",
    "This table reads the recorded metrics for hgb_v2_20261002T104801_398392Z; it does not describe a new training run. Test AP is 0.1948 versus 0.0077 for a constant-score reference. Better ranking does not remove the false-alert burden or establish operational value.",
) + "\n" + metric_table)

append_note("hgb-v2-product-explanation", bilingual(
    "From model to product | הצגת המוצר",
    "FastAPI חושף חיזוי יחיד ובאצווה, בדיקת בריאות ומידע על המודל. Streamlit מאפשר להזין ג'ובים, לראות תור התראות, פרטי חיזוי ומדדים. תור ההתראות מוגבל לסשן הנוכחי. בדיקות מומלצות מבוססות על כללים; עדיין אין SHAP או תרומות פיצ'רים לתחזית. הסימולטור מחשב תועלת צפויה: TP כפול שיעור מניעה משוער כפול עלות כשל, פחות עלות בדיקת כל ההתראות. לדוגמה, ב-Test ובהנחות של 25% מניעה, עלות כשל 100 ועלות בדיקה 10, התועלת נטו היא מינוס 137,060 יחידות עלות. זהו תרחיש משוער ולא חיסכון שנמדד.",
    "FastAPI exposes single/batch prediction, health, and model information. Streamlit provides job entry, a session-only alert queue, prediction details, and evaluation views. Recommended checks are rule-based; model feature attributions are not available. Simulated net benefit equals TP times assumed prevention rate times failure cost, minus the cost of reviewing every alert. Using Test counts with 25% prevention, failure cost 100, and review cost 10 gives -137,060 cost units. This is an assumed scenario, not measured savings.",
))

append_note("hgb-v2-rag-explanation", bilingual(
    "Local RAG | עוזר הידע",
    "עוזר הידע משתמש כעת במסמך Model Card אחד שחולק לשישה קטעים. EmbeddingGemma ממיר טקסט לווקטורים; האחזור בוחר שלושה קטעים לפי דמיון קוסינוס, ו-Qwen מנסח תשובה עם מקורות. הקוד בודק שמזהה המקור והציטוט קיימים בקטעים שאוחזרו. בדיקה זו אינה מוכיחה שהתשובה נובעת לוגית מהציטוט. אין במאגר לוגים של ג'ובים או תחקירי תקלות, והוא אינו מנבא את הכשל. יש להשלים benchmark לאחזור ולהרחיב את המקורות לצורך עוזר חקירת תקלות.",
    "The current knowledge base is one model card split into six chunks. EmbeddingGemma produces vectors, cosine similarity retrieves three chunks, and Qwen generates cited answers. Code validates retrieved source IDs and quote membership, but this does not prove semantic support for every claim. The corpus contains no individual job logs or incident reports. The LLM is not the failure predictor. A retrieval benchmark and a suitable investigation corpus remain to be added.",
))

audit_table = """| Area / specification section | Status on 2026-10-05 | Remaining work |
|---|---|---|
| Job grain and target, 6-7 | Aggregation and target logic inspected; validation scripts exist | Review current grain-contract evidence, including whether job_name separates executions |
| Pre-run feature gate, 7 | OPEN: availability is assumed | Prove availability for every input; exclude unsupported features from a strict pre-run model |
| Ingestion and dbt, 8-10 | Implemented components and successful reported builds | Verify current full dbt run, ingestion rerun/idempotency, and downstream failure blocking |
| Model ladder, 13 | No-skill, LR, HGB V1/V2 evaluated | Business heuristic and XGBoost candidate are missing from the current workflow |
| Temporal evaluation, 14 | Implemented; recorded metrics verified | Preserve the frozen report; further Test-informed tuning needs new evaluation data |
| Threshold policy, 14/16 | F1-selected threshold plus fixed-threshold simulator | Add cost/capacity policy comparison on development data; do not retune on this Test |
| Explainability, 15 | NOT IMPLEMENTED for HGB V2 | Validated model attributions or another suitable transparent equivalent |
| API and dashboard, 17-18 | Working local service and UI; smoke/parity results reported | Add attribution views, PR/threshold views, and actual ingestion/dbt quality reports |
| RAG, 19 + user scope | Working model-card assistant with citations and abstention examples | Labeled retrieval benchmark, simple retrieval baseline, and investigation corpus |
| Orchestration and packaging, 8/22 | Airflow/DAG and CI absent from the committed file list; no verified full service stack | Orchestrated workflow, complete demo packaging, and clean-environment verification |
| Reproducibility and tests, 21-22 | Core ML pins, saved artifact, API/inference/dashboard tests | Complete dependency record, training entry point, current full test run; CI is SHOULD HAVE |
"""

audit_intro = bilingual(
    "Specification review | מה תואם לתכנון ומה עדיין חסר",
    "הבדיקה מבוססת על המפרט בן 33 העמודים, המחברת, הקוד והפלטים ששותפו ורשימת 69 הקבצים ב-commit b7a392e. אין כאן אישור של כל הקבצים והבדיקות על המחשב המקומי. הפרויקט הוא דמו ניסיוני עובד, אך אינו עומד עדיין בכל דרישות המפרט. RAG הוא חובה לפי ההנחיה המעודכנת בפרויקט, למרות שב-PDF הוגדר כהרחבה מותנית. שימוש ב-HGB וב-risk_score מתאר את המימוש בפועל; אין לטעון שנבדק XGBoost או שבוצע כיול.",
    "This review uses the 33-page specification, shared notebook/code/output, and the 69-file commit b7a392e. It is not a complete audit or fresh test run of the local project. The experimental demo works, but full specification compliance is not established. RAG is required by the updated user scope, although conditional in the PDF. HGB and risk_score describe the implementation; XGBoost evaluation and calibration must not be claimed.",
)
append_note("hgb-v2-specification-review", audit_intro + "\n" + audit_table)

old_code = [c for c in before["cells"] if c["cell_type"] == "code"]
new_code = [c for c in notebook["cells"] if c["cell_type"] == "code"]

if old_code != new_code:
    raise SystemExit("Code cells or their outputs changed. No files written.")

audit_text = """# Implementation alignment with Master Specification v3

Review date: 2026-10-05. Reference: DataFlow_Sentinel_Master_Project_Specification_v3.pdf.
This replaces the earlier progress map, whose API, dashboard and RAG statuses were outdated.

## Evidence and limits

Reviewed the uploaded specification and notebook, supplied implementation code,
reported dbt/API/dashboard/RAG results, and the file list of commit b7a392e.
No fresh full-project test, database build, clean-install verification, or
end-to-end notebook execution was performed in this review. Unverified items
below remain open rather than being treated as passed.

## Recorded HGB V2 results

""" + metric_table + """

Threshold: 0.9696205830070223, selected by maximum Validation F1 and frozen before Test.
Scores are uncalibrated. AP is Average Precision, not a reported trapezoidal PR-AUC.
The reported 1,000-row parity check and HTTP smoke results support serving correctness.
They do not establish pre-run availability, causal explanations, or operational utility.

## Requirement status

""" + audit_table + """

## Interpretation and scope decisions

- RAG is required by the user's later instruction. The current implementation answers
  model-card questions; it is not yet the incident/runbook assistant described in section 19.
- HGB V2 is the current experimental model. The specification's XGBoost candidate
  and business heuristic have not been demonstrated in the current workflow.
- risk_score with score_is_calibrated=false accurately reflects the current model.
  Calibration is needed before interpreting these values as failure probabilities.
- main_risk_factors is empty and explanation_status is not_available. The deterministic
  playbook is not a substitute for model attributions or verified failure causes.
- The simulator implements the section-16 core formula and three prevention scenarios.
  Cost applies to every reviewed alert. It does not yet enforce team capacity or select a policy.
- Test has been inspected. Any Test-informed model or policy changes require a separate
  future evaluation period; the existing Test must not be described as newly untouched.
- The original mixed notebook is retained locally. The curated notebook's retained outputs
  belong to the original run; annotation changes do not constitute a rerun.

## Next work, in order

1. Close the grain and feature-availability evidence gaps, especially instance counts.
2. Add the missing development-set baselines and cost/capacity policy comparison.
3. Implement and validate model explanations for the final candidate.
4. Define a labeled RAG benchmark and a suitable documented investigation corpus.
5. Complete data-quality reporting, orchestration, packaging, training entry point,
   dependency documentation and fresh-environment tests before claiming full compliance.
"""

updates = {
    path: json.dumps(
        notebook, ensure_ascii=False, indent=1, allow_nan=False
    ) + "\n",
    audit_path: audit_text,
}

stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

for destination, content in updates.items():
    if destination.exists():
        if destination.read_text(encoding="utf-8-sig") == content:
            continue
        copy2(
            destination,
            destination.with_name(destination.name + ".bak-notes-" + stamp),
        )

    destination.write_text(content, encoding="utf-8")
    print("Updated:", destination.relative_to(root))

print(
    f"Bilingual notes added. {len(new_code)} code cells and their outputs preserved."
)
print("No model training or predictions were run.")
