# HGB V2 inference module

This addition loads the existing fitted HGB V2 pipeline and its metadata. It does not train, recalibrate, or select thresholds.

## Installation in the existing project

Extract the archive's contents into C:\project\dataflow-sentinel. Its paths are relative to that project root:

- src/ml/__init__.py
- src/ml/predictor.py
- tests/test_job_failure_predictor_v2.py
- docs/inference_v2.md

Use the existing training virtual environment. Dependencies are numpy, pandas, scikit-learn, joblib, and threadpoolctl (already used by the notebook). The exact training versions are recorded in the saved model's metadata.json. This module rejects a scikit-learn version mismatch.

Only load the project's own saved model artifact. There is no endpoint for uploading model files.

## Usage from the notebook

```python
from pathlib import Path
import sys

project_root = Path(r"C:\project\dataflow-sentinel")
sys.path.insert(0, str(project_root / "src"))
from ml.predictor import JobFailurePredictor

model_dir = (
    project_root / "artifacts" / "models"
    / "hgb_v2_20261002T104801_398392Z"
)
predictor = JobFailurePredictor(model_dir)
batch = predictor.predict_batch(X_test_v2.iloc[:10])
one = predictor.predict_one(X_test_v2.iloc[0].to_dict())
print(one)
```

The constructor accepts either the experiment directory or the exact model_bundle.joblib path. It loads the artifact once; reuse the instance across predictions.

## Input contract

Pass a DataFrame to predict_batch or a mapping to predict_one. Supply exactly the 12 feature names from predictor.feature_columns. Input column order may differ; row order and index are preserved. Extra columns, including IDs or failed_job, are rejected. Keep identifiers outside the feature mapping and associate batch results by their preserved row order/index.

The numeric feature dtypes and original float32 rounding are restored from model metadata. Numeric missing values remain missing; this wrapper does not invent replacements. Missing flags must be 0 or 1, task_count must be a positive integer, and total_instances must be a non-negative integer or missing. Infinite and unrepresentable values are rejected. This checks basic input validity; it does not verify how upstream aggregates were calculated or whether metadata existed at prediction time.

task_type_group is a non-empty trimmed string. Existing values such as type_10, mixed, missing, or partially_missing retain their meaning. New strings are passed to the fitted encoder, whose saved unknown-category policy maps them to NaN. No encoder is refitted.

## Outputs

predict_batch returns score, threshold, and alert columns. predict_one returns JSON-compatible values and adds model_name, model_created_at_utc, model_status, and score_is_calibrated=false.

The rule is score >= the saved full-precision threshold. For the recorded V2 experiment, that threshold is 0.9696205830070223. Scores are not calibrated failure probabilities. The known Test precision/recall limitations remain applicable.

Native prediction work is limited to four threads by default. Wrapper prediction calls are serialized within a process so overlapping thread-limit contexts cannot interfere. API capacity and concurrency will need their own evaluation.

## Verification

The contract tests build a small real sklearn pipeline in a temporary directory; they do not read the production artifact or alter its data. They cover prediction equivalence, reordered columns and row identity, JSON output, missing values, unseen categories, invalid inputs, and exact threshold boundaries.

All six tests passed during development with Python 3.12.14, scikit-learn 1.8.0, pandas 2.2.3, NumPy 2.3.5, and joblib 1.5.3. The owner's recorded model uses a different environment; its own notebook comparison below is the remaining integration check. Do not replace the training environment with these development versions.

Run from the project root with the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_job_failure_predictor_v2.py" -v
```

Then compare this wrapper against the notebook's previously computed scores using the actual saved artifact:

```python
import numpy as np

positions = np.linspace(
    0, len(X_test_v2) - 1,
    num=min(1000, len(X_test_v2)), dtype=int,
)
sample = X_test_v2.iloc[positions]
predictions = predictor.predict_batch(sample)
reference = np.asarray(hgb_v2_test_scores)[positions]

assert predictor.threshold == FINAL_THRESHOLD
np.testing.assert_allclose(predictions["score"], reference, rtol=0, atol=1e-12)
np.testing.assert_array_equal(
    predictions["alert"].to_numpy(), reference >= FINAL_THRESHOLD,
)
print(f"Verified {len(sample):,} predictions against the notebook.")
```

This is an integration check of existing predictions, not a new model evaluation or a threshold-selection step.

## References

- [scikit-learn model persistence](https://scikit-learn.org/stable/model_persistence.html)
- [OrdinalEncoder unknown-category behavior](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.OrdinalEncoder.html)
