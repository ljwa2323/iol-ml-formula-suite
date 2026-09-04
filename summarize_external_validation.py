# -*- coding: utf-8 -*-
# Summarize external validation Excel for paper tables.
# Run from project root: python summarize_external_validation.py
# Input: data/艾迪_cleaned_matched_杨宁格式_imputed_counterfactual_results_refined.xlsx

from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
INPATH_HILL = BASE / "data" / "艾迪_cleaned_matched_杨宁格式_imputed_counterfactual_results_refined_with_hillrbf.xlsx"
INPATH_BASE = BASE / "data" / "艾迪_cleaned_matched_杨宁格式_imputed_counterfactual_results_refined.xlsx"

# Model name in Excel -> paper display name
MODEL_DISPLAY = {
    "randomforest": "RandomForest",
    "xgboost": "XGBoost",
    "lightgbm": "LightGBM",
    "svm": "SVR",
    "nn": "MLP",
    "SRKT": "SRK-T",
    "Holladay1": "Holladay1",
    "Haigis": "Haigis",
    "Other": "Other",
    "BUII": "BUII",
    "Kane": "Kane",
    "HillRBF": "Hill-RBF",
    "EVO": "EVO",
}

POSTOP_SE_ABS_MAX = 10.0

# Models shown in main-text Table 11 / Figure 4 (exclude LightGBM, Other)
MAIN_TEXT_MODEL_KEYS = {
    "SRKT", "Holladay1", "Haigis", "HillRBF", "BUII", "EVO", "Kane",
    "xgboost", "randomforest", "svm", "nn",
}


def _find_column(df: pd.DataFrame, needle: str) -> str:
    matches = [c for c in df.columns if needle in str(c)]
    if not matches:
        raise ValueError(f"Column containing '{needle}' not found.")
    return matches[0]


def _valid_mask(df: pd.DataFrame) -> pd.Series:
    target_col = _find_column(df, "预留")
    postop_col = _find_column(df, "术后SE")
    target = pd.to_numeric(df[target_col], errors="coerce")
    postop = pd.to_numeric(df[postop_col], errors="coerce")
    return postop.abs() <= POSTOP_SE_ABS_MAX


def _metrics_from_counterfactual(
    df: pd.DataFrame,
    model_key: str,
    base_mask: pd.Series,
) -> dict | None:
    cf_col = f"{model_key}_counterfactual_SE"
    if cf_col not in df.columns:
        return None

    target_col = _find_column(df, "预留")
    target = pd.to_numeric(df[target_col], errors="coerce")
    cf = pd.to_numeric(df[cf_col], errors="coerce")

    mask = base_mask & cf.notna() & target.notna()
    if model_key == "HillRBF" and "白内障类型" in df.columns:
        mask &= df["白内障类型"].astype(str).str.strip() != "屈光术后"

    pe = cf[mask] - target[mask]
    if len(pe) == 0:
        return None

    ae = pe.abs()
    return {
        "Model": MODEL_DISPLAY.get(model_key, model_key),
        "MAE": float(ae.mean()),
        "RMSE": float(np.sqrt((pe**2).mean())),
        "pct_0.5D": float(100 * (ae <= 0.5).mean()),
        "pct_1.0D": float(100 * (ae <= 1.0).mean()),
        "n": int(mask.sum()),
    }


def main():
    inpath = INPATH_HILL if INPATH_HILL.exists() else INPATH_BASE
    if not inpath.exists():
        matches = list((BASE / "data").glob("*counterfactual_results_refined*.xlsx"))
        if not matches:
            print("File not found:", inpath)
            return
        inpath = matches[-1]

    print("Using input:", inpath)
    df = pd.read_excel(inpath, sheet_name=0)

    cf_cols = [c for c in df.columns if c.endswith("_counterfactual_SE")]
    if not cf_cols:
        print("No *_counterfactual_SE columns found. Columns:", list(df.columns)[:20])
        return

    base_mask_clean = _valid_mask(df)
    base_mask_raw = pd.Series(True, index=df.index)
    excluded = int((~base_mask_clean).sum())
    print("External validation counterfactual set N =", len(df))
    if excluded:
        print(f"Excluded {excluded} eye(s) with |postoperative SE| > {POSTOP_SE_ABS_MAX:.0f} D")
    print()

    def _collect(mask: pd.Series, model_filter: set[str] | None = None) -> pd.DataFrame:
        rows = []
        for col in sorted(cf_cols):
            model_key = col.replace("_counterfactual_SE", "")
            if model_filter is not None and model_key not in model_filter:
                continue
            metrics = _metrics_from_counterfactual(df, model_key, mask)
            if metrics is not None:
                rows.append(metrics)
        res = pd.DataFrame(rows).round(4)
        if not res.empty:
            res["pct_0.5D"] = res["pct_0.5D"].round(2)
            res["pct_1.0D"] = res["pct_1.0D"].round(2)
        return res

    cleaned = _collect(base_mask_clean, MAIN_TEXT_MODEL_KEYS)
    raw = _collect(base_mask_raw, MAIN_TEXT_MODEL_KEYS)

    print("Cleaned sensitivity analysis (n = 257):")
    print(cleaned.to_string(index=False))
    print()
    print("Original counterfactual analysis (n = 258):")
    print(raw.to_string(index=False))
    print()

    out = BASE / "results" / "external_validation_summary.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    cleaned[["Model", "MAE", "RMSE", "pct_0.5D", "pct_1.0D"]].to_csv(
        out, index=False, encoding="utf-8"
    )
    raw[["Model", "MAE", "RMSE", "pct_0.5D", "pct_1.0D"]].to_csv(
        BASE / "results" / "external_validation_summary_n258.csv",
        index=False,
        encoding="utf-8",
    )
    print("Saved:", out)
    print("Saved:", BASE / "results" / "external_validation_summary_n258.csv")


if __name__ == "__main__":
    main()
