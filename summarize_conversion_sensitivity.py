# -*- coding: utf-8 -*-
"""
Sensitivity analysis for IOL-to-SE conversion factor in external counterfactual evaluation.

Recomputes:
  counterfactual_SE = postoperative_SE + k * diff_IOL
  error_SE = |counterfactual_SE - target_SE|

for k in {0.6, 0.7, 0.8}, without re-running ML/formula optimization.

Run from project root:
  python summarize_conversion_sensitivity.py
"""

from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
INPATH_HILL = BASE / "data" / "艾迪_cleaned_matched_杨宁格式_imputed_counterfactual_results_refined_with_hillrbf.xlsx"
INPATH_BASE = BASE / "data" / "艾迪_cleaned_matched_杨宁格式_imputed_counterfactual_results_refined.xlsx"

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

MAIN_TEXT_MODEL_ORDER = [
    "SRKT",
    "Holladay1",
    "Haigis",
    "BUII",
    "EVO",
    "Kane",
    "HillRBF",
    "xgboost",
    "randomforest",
    "svm",
    "nn",
]

POSTOP_SE_ABS_MAX = 10.0
CONVERSION_FACTORS = (0.6, 0.7, 0.8)


def _find_column(df: pd.DataFrame, needle: str) -> str:
    matches = [c for c in df.columns if needle in str(c)]
    if not matches:
        raise ValueError(f"Column containing '{needle}' not found.")
    return matches[0]


def _valid_mask(df: pd.DataFrame) -> pd.Series:
    postop_col = _find_column(df, "术后SE")
    postop = pd.to_numeric(df[postop_col], errors="coerce")
    return postop.abs() <= POSTOP_SE_ABS_MAX


def _metrics_for_factor(
    df: pd.DataFrame,
    model_key: str,
    base_mask: pd.Series,
    factor: float,
    baseline_factor: float = 0.7,
) -> dict | None:
    """
    Prefer stored *_counterfactual_SE (assumed computed with baseline_factor=0.7).
    Rescale: CF_k = postop + (k / 0.7) * (CF_0.7 - postop).

    Falls back to *_diff_IOL if counterfactual_SE is missing.
    """
    cf_col = f"{model_key}_counterfactual_SE"
    diff_col = f"{model_key}_diff_IOL"
    target_col = _find_column(df, "预留")
    postop_col = _find_column(df, "术后SE")
    target = pd.to_numeric(df[target_col], errors="coerce")
    postop = pd.to_numeric(df[postop_col], errors="coerce")

    mask = base_mask & target.notna() & postop.notna()
    if model_key == "HillRBF" and "白内障类型" in df.columns:
        mask &= df["白内障类型"].astype(str).str.strip() != "屈光术后"

    if cf_col in df.columns:
        cf0 = pd.to_numeric(df[cf_col], errors="coerce")
        mask = mask & cf0.notna()
        if int(mask.sum()) == 0:
            return None
        # CF_k = postop + (k/0.7)*(CF_0.7 - postop)
        cf = postop[mask] + (factor / baseline_factor) * (cf0[mask] - postop[mask])
    elif diff_col in df.columns:
        diff = pd.to_numeric(df[diff_col], errors="coerce")
        mask = mask & diff.notna()
        if int(mask.sum()) == 0:
            return None
        cf = postop[mask] + factor * diff[mask]
    else:
        return None

    pe = cf - target[mask]
    ae = pe.abs()
    return {
        "conversion_factor": factor,
        "Model": MODEL_DISPLAY.get(model_key, model_key),
        "model_key": model_key,
        "MAE": float(ae.mean()),
        "RMSE": float(np.sqrt((pe**2).mean())),
        "pct_0.5D": float(100 * (ae <= 0.5).mean()),
        "pct_1.0D": float(100 * (ae <= 1.0).mean()),
        "n": int(mask.sum()),
    }


def main() -> None:
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
    diff_cols = [c for c in df.columns if c.endswith("_diff_IOL")]
    available_keys = {c.replace("_counterfactual_SE", "") for c in cf_cols} | {
        c.replace("_diff_IOL", "") for c in diff_cols
    }
    if not available_keys:
        print("No *_counterfactual_SE or *_diff_IOL columns found.")
        return

    model_keys = [k for k in MAIN_TEXT_MODEL_ORDER if k in available_keys]
    missing = [k for k in MAIN_TEXT_MODEL_ORDER if k not in available_keys]
    if missing:
        print("Missing models (skipped):", missing)
    print("Using stored counterfactual_SE rescaled from baseline k=0.7")

    base_mask = _valid_mask(df)
    excluded = int((~base_mask).sum())
    print("External validation counterfactual set N =", len(df))
    if excluded:
        print(f"Excluded {excluded} eye(s) with |postoperative SE| > {POSTOP_SE_ABS_MAX:.0f} D")
    print("Cleaned analysis N =", int(base_mask.sum()))
    print()

    rows = []
    for factor in CONVERSION_FACTORS:
        for model_key in model_keys:
            metrics = _metrics_for_factor(df, model_key, base_mask, factor)
            if metrics is not None:
                rows.append(metrics)

    res = pd.DataFrame(rows)
    if res.empty:
        print("No metrics computed.")
        return

    res["MAE"] = res["MAE"].round(4)
    res["RMSE"] = res["RMSE"].round(4)
    res["pct_0.5D"] = res["pct_0.5D"].round(2)
    res["pct_1.0D"] = res["pct_1.0D"].round(2)

    out_dir = BASE / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_long = out_dir / "external_validation_conversion_sensitivity.csv"
    res[["conversion_factor", "Model", "MAE", "RMSE", "pct_0.5D", "pct_1.0D", "n"]].to_csv(
        out_long, index=False, encoding="utf-8"
    )

    # Wide MAE table for paper-friendly comparison
    mae_wide = (
        res.pivot(index="Model", columns="conversion_factor", values="MAE")
        .reindex([MODEL_DISPLAY[k] for k in model_keys])
        .rename(columns={0.6: "MAE_k0.6", 0.7: "MAE_k0.7", 0.8: "MAE_k0.8"})
    )
    out_wide = out_dir / "external_validation_conversion_sensitivity_mae_wide.csv"
    mae_wide.to_csv(out_wide, encoding="utf-8")

    for factor in CONVERSION_FACTORS:
        sub = res[res["conversion_factor"] == factor][
            ["Model", "MAE", "RMSE", "pct_0.5D", "pct_1.0D", "n"]
        ]
        print(f"=== conversion factor k = {factor} (1 D IOL -> {factor} D SE) ===")
        print(sub.to_string(index=False))
        print()

    print("Saved:", out_long)
    print("Saved:", out_wide)


if __name__ == "__main__":
    main()
