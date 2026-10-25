"""Train the experimental classifier for the supplied water quality dataset.

Run from the backend directory: python train_model.py
The model predicts dataset Water_Quality categories; it is not a drinking-water
potability certification model.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "ml model" / "Water Quality Classification for Rural Areas.csv"
ARTIFACT = Path(__file__).resolve().parent / "app" / "water_quality_model.joblib"
FEATURES = ("pH", "TDS_ppm", "Turbidity_NTU", "Temperature_C")


def main() -> None:
    rows: list[list[float]] = []
    labels: list[str] = []
    with DATASET.open(newline="", encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            rows.append([float(row[name]) for name in FEATURES])
            label = row["Water_Quality"].strip().title()
            if label not in {"Good", "Moderate", "Poor"}:
                raise ValueError(f"Unexpected Water_Quality label: {row['Water_Quality']!r}")
            labels.append(label)

    x_train, x_test, y_train, y_test = train_test_split(
        rows, labels, test_size=0.2, random_state=42, stratify=labels
    )
    model = RandomForestClassifier(
        n_estimators=500, min_samples_leaf=2, class_weight="balanced_subsample",
        max_features="sqrt", random_state=42, n_jobs=-1,
    )
    model.fit(x_train, y_train)
    predictions = model.predict(x_test)
    metrics = {
        "rows": len(rows),
        "holdout_rows": len(y_test),
        "accuracy": round(float(accuracy_score(y_test, predictions)), 6),
        "macro_f1": round(float(f1_score(y_test, predictions, average="macro", zero_division=0)), 6),
        "classification_report": classification_report(
            y_test, predictions, labels=["Good", "Moderate", "Poor"],
            target_names=["Good", "Moderate", "Poor"], output_dict=True, zero_division=0,
        ),
        "class_counts": {label: labels.count(label) for label in ("Good", "Moderate", "Poor")},
        "features_used": list(FEATURES),
        "omitted_dataset_features": ["Conductivity_uS_cm", "Dissolved_Oxygen_mg_L"],
        "validation_note": "Random stratified holdout; only 10 Good samples are present, so this score is highly uncertain. Dataset has no timestamps or device/source identifiers.",
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    import joblib

    joblib.dump({"model": model, "features": list(FEATURES), "labels": list(model.classes_)}, ARTIFACT)
    (ARTIFACT.parent / "water_quality_model_metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2))
    print(f"Saved model: {ARTIFACT}")


if __name__ == "__main__":
    main()
