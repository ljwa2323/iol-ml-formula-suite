# -*- coding: utf-8 -*-
"""
Given a trained ML pipeline (post-SE prediction), find optimal IOL by numerical methods
so that predicted 术后SE is as close as possible to a target (preset) SE.

Usage:
  1. Train and save pipeline: python ml_postSE_models.py --save-models
  2. Load pipeline and call find_optimal_iol() or run this script.

  From code:
    from ml_optimal_iol import load_pipeline, predict_post_SE, find_optimal_iol
    pipe = load_pipeline()
    iol, pred_se, err = find_optimal_iol({"AL": 24.5, "ACD": 3.0, ...}, target_SE=-0.5, model_name="RandomForest")
"""

from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
DEFAULT_PIPELINE_PATH = BASE / "results" / "ml_postSE_pipeline.joblib"

# Which models in the pipeline were trained on scaled features (must match ml_postSE_models.py)
USE_SCALED = ["LinearRegression", "SVR", "MLP"]

# Columns required for external validation (must include 术后SE as actual)
EVAL_FEAT_COLS = ["AL", "ACD", "LT", "CCT", "W2W", "K1", "K2", "预留", "IOL"]
EVAL_ACTUAL_SE_COL = "术后SE"

# Linear IOL-refraction conversion for counterfactual evaluation (retrospective):
# 1 D IOL change ~ 0.7 D postoperative SE change => Delta_IOL = 0.7 * Delta_SE
# IOL_theoretical = IOL_implanted + 0.7 * (SE_observed - SE_target)
LINEAR_IOL_PER_SE = 0.7


def load_pipeline(path=None):
    """Load saved pipeline (imputer, scaler, models, feat_cols) from joblib."""
    p = path if path is not None else DEFAULT_PIPELINE_PATH
    p = Path(p)
    if not p.is_absolute():
        p = BASE / p
    if not p.exists():
        raise FileNotFoundError("Pipeline not found: %s. Run: python ml_postSE_models.py --save-models" % p)
    import joblib
    pipeline = joblib.load(p)
    imputer = pipeline.get("imputer") if isinstance(pipeline, dict) else None
    # Compatibility fix for pipelines trained with older sklearn versions.
    # sklearn 1.8 expects SimpleImputer._fill_dtype, while old pickles may only
    # contain _fit_dtype, causing transform() to fail with AttributeError.
    if imputer is not None and (not hasattr(imputer, "_fill_dtype")) and hasattr(imputer, "_fit_dtype"):
        imputer._fill_dtype = imputer._fit_dtype
    return pipeline


def _row_to_X(row_dict, feat_cols, imputer, scaler, use_scaled):
    """Build one row of features, impute, optionally scale. Returns array for predict."""
    row = pd.DataFrame([row_dict])[feat_cols]
    X_imp = imputer.transform(row)
    # Keep DataFrame so scaler receives feature names (avoids sklearn warning)
    if not hasattr(X_imp, "columns"):
        X_imp = pd.DataFrame(X_imp, columns=feat_cols)
    X_scaled = scaler.transform(X_imp)
    if use_scaled:
        return X_scaled
    return np.asarray(X_imp)


def predict_post_SE(biometry, IOL, pipeline, model_name=None):
    """
    Predict 术后SE for given biometry and IOL.

    biometry: dict with keys AL, ACD, LT, CCT, W2W, K1, K2, 预留 (missing keys will be NaN and imputed)
    IOL: float (D)
    pipeline: from load_pipeline()
    model_name: e.g. "RandomForest", "LinearRegression". If None, uses first available model.

    Returns: predicted 术后SE (float)
    """
    feat_cols = pipeline["feat_cols"]
    imputer = pipeline["imputer"]
    scaler = pipeline["scaler"]
    models = pipeline["models"]

    if model_name is None:
        model_name = next(iter(models))
    if model_name not in models:
        raise KeyError("Unknown model: %s. Available: %s" % (model_name, list(models)))

    row = {c: biometry.get(c, np.nan) for c in feat_cols}
    row["IOL"] = IOL
    # ensure order and present keys
    row = {c: row.get(c, np.nan) for c in feat_cols}

    use_scaled = model_name in USE_SCALED
    X = _row_to_X(row, feat_cols, imputer, scaler, use_scaled)
    return float(models[model_name].predict(X)[0])


def find_optimal_iol(
    biometry,
    target_SE,
    pipeline,
    model_name=None,
    iol_bounds=(5.0, 35.0),
    iol_step=0.5,
    method="grid",
):
    """
    Find IOL that minimizes |predicted 术后SE - target_SE|.

    biometry: dict with keys AL, ACD, LT, CCT, W2W, K1, K2, 预留
    target_SE: desired 术后SE (D), e.g. -0.5 for slight myopia
    pipeline: from load_pipeline()
    model_name: which model to use; default first in pipeline
    iol_bounds: (iol_min, iol_max) in D
    iol_step: step for grid (D); result is rounded to this grid
    method: "grid" (robust, works for any model) or "minimize" (scipy, continuous then round)

    Returns:
        best_iol: float, on the iol_step grid
        predicted_se: predicted 术后SE at best_iol
        error: |predicted_se - target_SE|
    """
    if model_name is None:
        model_name = next(iter(pipeline["models"]))

    def objective(iol):
        pred = predict_post_SE(biometry, float(iol), pipeline, model_name)
        return (pred - target_SE) ** 2

    if method == "grid":
        iol_min, iol_max = iol_bounds
        grid = np.arange(iol_min, iol_max + 1e-9, iol_step)
        best_iol = None
        best_err = np.inf
        best_pred = None
        for iol in grid:
            pred = predict_post_SE(biometry, float(iol), pipeline, model_name)
            err = abs(pred - target_SE)
            if err < best_err:
                best_err = err
                best_iol = float(iol)
                best_pred = pred
        return best_iol, best_pred, best_err

    if method == "minimize":
        from scipy.optimize import minimize_scalar
        iol_min, iol_max = iol_bounds
        res = minimize_scalar(objective, bounds=(iol_min, iol_max), method="bounded")
        iol_cont = res.x
        # round to grid
        best_iol = round(iol_cont / iol_step) * iol_step
        best_iol = max(iol_min, min(iol_max, best_iol))
        best_pred = predict_post_SE(biometry, best_iol, pipeline, model_name)
        best_err = abs(best_pred - target_SE)
        return best_iol, best_pred, best_err

    raise ValueError("method must be 'grid' or 'minimize'")


def find_five_iol_options(
    biometry,
    target_SE,
    pipeline,
    model_name=None,
    iol_bounds=(5.0, 35.0),
    iol_step=0.5,
):
    """
    Return 5 IOL options centered on the optimal (grid step 0.5 D), with predicted 术后SE.
    Optimal is in the middle (index 2). Same style as common IOL calculators.

    Returns: list of 5 dicts [{"iol": float, "pred_se": float, "is_optimal": bool}, ...]
    """
    best_iol, best_pred, _ = find_optimal_iol(
        biometry, target_SE, pipeline, model_name=model_name,
        iol_bounds=iol_bounds, iol_step=iol_step, method="grid",
    )
    iol_min, iol_max = iol_bounds
    offsets = [-1.0, -0.5, 0.0, 0.5, 1.0]
    results = []
    for i, off in enumerate(offsets):
        iol = round((best_iol + off) / iol_step) * iol_step
        iol = max(iol_min, min(iol_max, iol))
        pred_se = predict_post_SE(biometry, iol, pipeline, model_name)
        results.append({
            "iol": round(iol, 2),
            "pred_se": round(pred_se, 4),
            "is_optimal": (i == 2),
        })
    return results


def evaluate_external(pipeline, excel_path, model_name=None, actual_se_col=None):
    """
    Evaluate pipeline on external validation set: predict 术后SE for each row
    (using actual IOL) and compare to actual 术后SE. Drop rows missing required
    cols or actual SE.

    pipeline: from load_pipeline()
    excel_path: path to Excel (e.g. 艾迪_cleaned_matched_杨宁格式.xlsx)
    model_name: which model; default first in pipeline
    actual_se_col: column name for actual 术后SE; default EVAL_ACTUAL_SE_COL

    Returns: dict with keys n_total, n_eval, mae, rmse, r2, pct_within_05, pct_within_075, pct_within_10
    """
    actual_se_col = actual_se_col or EVAL_ACTUAL_SE_COL
    required = EVAL_FEAT_COLS + [actual_se_col]
    df = pd.read_excel(excel_path)
    for c in required:
        if c not in df.columns:
            raise ValueError("External Excel missing column '%s'. Got: %s" % (c, list(df.columns)))
    # drop rows with any missing in required
    use = df[required].copy()
    for c in EVAL_FEAT_COLS:
        use[c] = pd.to_numeric(use[c], errors="coerce")
    use[actual_se_col] = pd.to_numeric(use[actual_se_col], errors="coerce")
    valid = use.notna().all(axis=1)
    use = use.loc[valid].copy()
    n_total = len(df)
    n_eval = len(use)
    if n_eval == 0:
        return {"n_total": n_total, "n_eval": 0, "mae": np.nan, "rmse": np.nan, "r2": np.nan,
                "pct_within_05": np.nan, "pct_within_075": np.nan, "pct_within_10": np.nan}

    if model_name is None:
        model_name = next(iter(pipeline["models"]))
    feat_cols = pipeline["feat_cols"]
    imputer = pipeline["imputer"]
    scaler = pipeline["scaler"]
    model = pipeline["models"][model_name]
    use_scaled = model_name in USE_SCALED

    y_true = use[actual_se_col].values
    preds = []
    for i, row in use.iterrows():
        row_dict = row[EVAL_FEAT_COLS].to_dict()
        row_dict = {c: row_dict.get(c, np.nan) for c in feat_cols}
        X = _row_to_X(row_dict, feat_cols, imputer, scaler, use_scaled)
        preds.append(float(model.predict(X)[0]))
    y_pred = np.array(preds)

    mae = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    r2 = float(1 - ss_res / ss_tot) if ss_tot != 0 else np.nan
    pct_05 = 100 * np.mean(np.abs(y_true - y_pred) <= 0.5)
    pct_075 = 100 * np.mean(np.abs(y_true - y_pred) <= 0.75)
    pct_10 = 100 * np.mean(np.abs(y_true - y_pred) <= 1.0)

    return {
        "n_total": n_total,
        "n_eval": n_eval,
        "mae": mae,
        "rmse": rmse,
        "r2": r2,
        "pct_within_05": pct_05,
        "pct_within_075": pct_075,
        "pct_within_10": pct_10,
    }


def evaluate_external_counterfactual(
    pipeline,
    excel_path,
    model_name=None,
    iol_bounds=(5.0, 35.0),
    iol_step=0.5,
    output_path=None,
):
    """
    Counterfactual evaluation: use ML optimal IOL vs implanted IOL to derive
    counterfactual postoperative SE, then compare with target (预留).

    Step 1: Drop rows where IOL, 预留, or 术后SE is missing.
    Step 2: For each row with full biometry, find ML_optimal IOL (target = 预留).
    Step 3: diff = ML_optimal - IOL_implanted.
    Step 4: counterfactual_SE = 术后SE + 0.7 * diff (linear: 1 D IOL -> 0.7 D SE).
    Step 5: error = |counterfactual_SE - 预留|. Report MAE, RMSE, %% within 0.5/1.0 D (SE).

    If output_path is set, saves dataframe with new columns: ML_optimal_IOL, diff_IOL, counterfactual_SE, error_SE.

    Returns: dict with n_total, n_after_iol_se_filter, n_eval, mae_se, rmse_se, pct_within_05_d, pct_within_10_d, result_df
    """
    df = pd.read_excel(excel_path)
    for c in ["IOL", "预留", EVAL_ACTUAL_SE_COL]:
        if c not in df.columns:
            raise ValueError("External Excel missing column '%s'. Got: %s" % (c, list(df.columns)))

    # Step 1: drop rows with missing IOL, 预留, or 术后SE
    use = df[["IOL", "预留", EVAL_ACTUAL_SE_COL]].copy()
    use["IOL"] = pd.to_numeric(use["IOL"], errors="coerce")
    use["预留"] = pd.to_numeric(use["预留"], errors="coerce")
    use[EVAL_ACTUAL_SE_COL] = pd.to_numeric(use[EVAL_ACTUAL_SE_COL], errors="coerce")
    valid_iol_se = use.notna().all(axis=1)
    df1 = df.loc[valid_iol_se].copy()
    n_total = len(df)
    n_after_iol_se_filter = len(df1)

    # Need biometry for find_optimal_iol
    for c in EVAL_FEAT_COLS:
        if c not in df1.columns:
            raise ValueError("External Excel missing column '%s' for biometry." % c)
    for c in EVAL_FEAT_COLS:
        df1[c] = pd.to_numeric(df1[c], errors="coerce")
    df1[EVAL_ACTUAL_SE_COL] = pd.to_numeric(df1[EVAL_ACTUAL_SE_COL], errors="coerce")
    valid_bio = df1[EVAL_FEAT_COLS + [EVAL_ACTUAL_SE_COL]].notna().all(axis=1)
    df2 = df1.loc[valid_bio].copy()
    n_eval = len(df2)

    if n_eval == 0:
        return {
            "n_total": n_total,
            "n_after_iol_se_filter": n_after_iol_se_filter,
            "n_eval": 0,
            "mae_se": np.nan,
            "rmse_se": np.nan,
            "pct_within_05_d": np.nan,
            "pct_within_10_d": np.nan,
            "result_df": None,
        }

    if model_name is None:
        model_name = next(iter(pipeline["models"]))

    ml_optimal_list = []
    diff_list = []
    counterfactual_se_list = []
    errors_se_list = []
    for _, row in df2.iterrows():
        biometry = {c: row[c] for c in EVAL_FEAT_COLS if c != "IOL"}
        biometry["预留"] = row["预留"]
        ml_optimal, _, _ = find_optimal_iol(
            biometry,
            target_SE=float(row["预留"]),
            pipeline=pipeline,
            model_name=model_name,
            iol_bounds=iol_bounds,
            iol_step=iol_step,
            method="grid",
        )
        diff = ml_optimal - row["IOL"]
        counterfactual_se = row[EVAL_ACTUAL_SE_COL] + LINEAR_IOL_PER_SE * diff
        err = abs(counterfactual_se - row["预留"])
        ml_optimal_list.append(ml_optimal)
        diff_list.append(diff)
        counterfactual_se_list.append(counterfactual_se)
        errors_se_list.append(err)

    df2 = df2.copy()
    df2["ML_optimal_IOL"] = ml_optimal_list
    df2["diff_IOL"] = diff_list
    df2["counterfactual_SE"] = counterfactual_se_list
    df2["error_SE"] = errors_se_list

    errors_se = np.array(errors_se_list)
    mae_se = float(np.mean(errors_se))
    rmse_se = float(np.sqrt(np.mean(errors_se ** 2)))
    pct_05 = 100 * np.mean(errors_se <= 0.5)
    pct_10 = 100 * np.mean(errors_se <= 1.0)

    if output_path:
        path = Path(output_path)
        if not path.is_absolute():
            path = BASE / path
        path.parent.mkdir(parents=True, exist_ok=True)
        df2.to_excel(path, index=False)

    return {
        "n_total": n_total,
        "n_after_iol_se_filter": n_after_iol_se_filter,
        "n_eval": n_eval,
        "mae_se": mae_se,
        "rmse_se": rmse_se,
        "pct_within_05_d": pct_05,
        "pct_within_10_d": pct_10,
        "result_df": df2,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Find optimal IOL from ML pipeline for target 术后SE.")
    parser.add_argument("--pipeline", type=str, default=None, help="Path to ml_postSE_pipeline.joblib")
    parser.add_argument("--model", type=str, default="RandomForest", help="Model name")
    parser.add_argument("--target-se", type=float, default=-0.5, help="Target 术后SE (D)")
    parser.add_argument("--method", choices=["grid", "minimize"], default="grid")
    parser.add_argument("--iol-min", type=float, default=5.0)
    parser.add_argument("--iol-max", type=float, default=35.0)
    parser.add_argument("--iol-step", type=float, default=0.5)
    # external validation set
    parser.add_argument("--external", type=str, default=None,
                        help="Path to external validation Excel (e.g. data/艾迪_cleaned_matched_杨宁格式.xlsx)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output Excel path for counterfactual results (with new columns). Default: data/..._counterfactual_results.xlsx")
    # example biometry (one row for demo)
    parser.add_argument("--AL", type=float, default=24.0)
    parser.add_argument("--ACD", type=float, default=3.0)
    parser.add_argument("--LT", type=float, default=4.5)
    parser.add_argument("--CCT", type=float, default=550.0)
    parser.add_argument("--W2W", type=float, default=11.8)
    parser.add_argument("--K1", type=float, default=43.0)
    parser.add_argument("--K2", type=float, default=44.0)
    parser.add_argument("--reserve", type=float, default=-0.5, dest="reserve", help="预留 (D)")
    args = parser.parse_args()

    pipeline = load_pipeline(args.pipeline)

    if args.external:
        # Counterfactual evaluation: drop rows missing IOL/预留/术后SE, then compare ML_optimal vs counterfactual SE
        ext_path = Path(args.external)
        if not ext_path.is_absolute():
            ext_path = BASE / ext_path
        if not ext_path.exists():
            raise FileNotFoundError("External file not found: %s" % ext_path)
        out_path = args.output
        if not out_path:
            out_path = ext_path.parent / (ext_path.stem + "_counterfactual_results.xlsx")
        metrics = evaluate_external_counterfactual(
            pipeline,
            ext_path,
            model_name=args.model,
            iol_bounds=(args.iol_min, args.iol_max),
            iol_step=args.iol_step,
            output_path=out_path,
        )
        print("External validation (counterfactual SE): %s" % ext_path)
        print("  diff = ML_optimal - IOL_implanted; counterfactual_SE = 术后SE + 0.7*diff; error = |counterfactual_SE - 预留|")
        print("  Rows total: %d" % metrics["n_total"])
        print("  After dropping missing IOL/预留/术后SE: %d" % metrics["n_after_iol_se_filter"])
        print("  Evaluated (full biometry): %d" % metrics["n_eval"])
        if metrics["n_eval"] > 0:
            print("  MAE (SE D): %.4f" % metrics["mae_se"])
            print("  RMSE (SE D): %.4f" % metrics["rmse_se"])
            print("  %% within 0.5 D SE: %.1f" % metrics["pct_within_05_d"])
            print("  %% within 1.0 D SE: %.1f" % metrics["pct_within_10_d"])
            print("  Output (with ML_optimal_IOL, diff_IOL, counterfactual_SE, error_SE): %s" % out_path)
        return

    biometry = {
        "AL": args.AL, "ACD": args.ACD, "LT": args.LT,
        "CCT": args.CCT, "W2W": args.W2W, "K1": args.K1, "K2": args.K2,
        "预留": args.reserve,
    }

    best_iol, pred_se, err = find_optimal_iol(
        biometry,
        target_SE=args.target_se,
        pipeline=pipeline,
        model_name=args.model,
        iol_bounds=(args.iol_min, args.iol_max),
        iol_step=args.iol_step,
        method=args.method,
    )
    print("Target 术后SE (D):", args.target_se)
    print("Best IOL (D):", best_iol)
    print("Predicted 术后SE (D):", round(pred_se, 4))
    print("|pred - target| (D):", round(err, 4))


if __name__ == "__main__":
    main()
