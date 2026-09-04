# -*- coding: utf-8 -*-
"""
ML models for predicting 术后SE from biometry + 预留 + IOL.
Data: data/杨宁整合四文件合并_公式计算结果_merged_SE_pred.xlsx
Models: Linear Regression, SVR, Random Forest, XGBoost, MLP.
Train/test split: stratified by 白内障类型. Test metrics: overall + per cataract type.
Requires: pandas, openpyxl, scikit-learn, matplotlib. Optional: xgboost, seaborn, shap.

Run from project root (activate env first, e.g. conda activate py311):
  python ml_postSE_models.py
  python ml_postSE_models.py --save-models
  python ml_postSE_models.py --no-shap   # skip SHAP if slow or shap not installed
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR
from sklearn.ensemble import RandomForestRegressor

try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

try:
    import shap
    HAS_SHAP = True
except ImportError:
    HAS_SHAP = False

BASE = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE / "data" / "杨宁整合四文件合并_公式计算结果_merged_SE_pred.xlsx"

FEAT_NAMES = ["AL", "ACD", "LT", "CCT", "W2W", "K1", "K2", "预留", "IOL"]
MULTIMODAL_COLS = ["B超", "A", "T", "N"]
TARGET_NAME = "术后SE"
CAT_TYPE_COL = "白内障类型"
RANDOM_STATE = 42
TEST_SIZE = 0.2
MIN_STRATUM_SIZE = 2  # min samples per stratum for stratify
MIN_SUBGROUP_SIZE = 5  # min samples per AL/K subgroup for reporting

# AL subgroups (mm): 26-28, 28-30, >=30 (per method 1.3)
AL_LEVELS = ["26-28mm", "28-30mm", ">=30mm"]
# K subgroups (D): flat <40, 40-46, >=46
K_LEVELS = ["K<40D", "40-46D", ">=46D"]


def _to_numeric(ser):
    return pd.to_numeric(ser, errors="coerce")


def _build_atn_score(df):
    """
    Build ATN score from A/T/N components according to ATN staging:
      A: 0-4
      T: 0-5
      N: N0/NO->0, N1->1, N2a/N2s/N2->2
    Returns numeric Series with NaN if any component is unavailable.
    """
    if not all(c in df.columns for c in ["A", "T", "N"]):
        return pd.Series(np.nan, index=df.index)
    a_num = pd.to_numeric(df["A"], errors="coerce")
    t_num = pd.to_numeric(df["T"], errors="coerce")
    n_raw = df["N"]
    n_str = n_raw.astype(str).str.strip().str.upper()
    n_num = pd.to_numeric(n_raw, errors="coerce")
    n_code = pd.Series(np.nan, index=df.index, dtype=float)
    n_code[n_str.isin(["N0", "NO", "0"])] = 0.0
    n_code[n_str.isin(["N1", "1"])] = 1.0
    n_code[n_str.isin(["N2", "N2A", "N2S", "2"])] = 2.0
    n_code[n_code.isna()] = n_num[n_code.isna()]
    return a_num + t_num + n_code


def mae(y, yhat):
    return mean_absolute_error(y, yhat)


def rmse(y, yhat):
    return np.sqrt(mean_squared_error(y, yhat))


def medae(y, yhat):
    return np.median(np.abs(np.asarray(y) - np.asarray(yhat)))


def r2(y, yhat):
    return r2_score(y, yhat)


def pct_within(y, yhat, d):
    return 100 * np.mean(np.abs(np.asarray(y) - np.asarray(yhat)) <= d)


def compute_shap_ranking(estimator, X_train, feature_names, model_name, max_background=200, nsamples_kernel=100):
    """
    Compute mean absolute SHAP per feature and return a DataFrame with Model, Feature, mean_abs_shap, rank.
    X_train: numpy array used to train the model (same format as model was fit on).
    """
    if not HAS_SHAP:
        return None
    X_train = np.asarray(X_train)
    if len(X_train) > max_background:
        rng = np.random.default_rng(RANDOM_STATE)
        idx = rng.choice(len(X_train), size=max_background, replace=False)
        X_bg = X_train[idx]
    else:
        X_bg = X_train
    try:
        if model_name in ("RandomForest", "XGBoost"):
            explainer = shap.TreeExplainer(estimator, X_bg)
            shap_vals = explainer.shap_values(X_bg)
            if isinstance(shap_vals, list):
                shap_vals = shap_vals[0]
        elif model_name == "LinearRegression":
            masker = shap.maskers.Independent(X_bg)
            explainer = shap.LinearExplainer(estimator, masker)
            shap_vals = explainer.shap_values(X_bg)
        else:
            explainer = shap.KernelExplainer(estimator.predict, X_bg)
            shap_vals = explainer.shap_values(X_bg, nsamples=min(nsamples_kernel, len(X_bg) * 2))
        shap_vals = np.asarray(shap_vals)
        if shap_vals.ndim == 3:
            shap_vals = shap_vals[0]
        mean_abs = np.abs(shap_vals).mean(axis=0)
        order = np.argsort(-mean_abs)
        rows = []
        for r, j in enumerate(order):
            rows.append({
                "Model": model_name,
                "Feature": feature_names[j],
                "mean_abs_shap": float(mean_abs[j]),
                "rank": r + 1,
            })
        return pd.DataFrame(rows)
    except Exception as e:
        print("  SHAP failed for %s: %s" % (model_name, e))
        return None


def compute_shap_ranking_and_plots(
    estimator,
    X_train,
    feature_names,
    model_name,
    res_dir,
    prefix="",
    max_background=200,
    nsamples_kernel=100,
):
    """
    Compute SHAP ranking (same as compute_shap_ranking), save SHAP values to .npz,
    and save SHAP summary (bar) and beeswarm plots for this model. Returns ranking DataFrame or None.
    prefix: optional prefix for filenames, e.g. 'formula_feat_', 'multimodal_'.
    To replot from saved .npz without recomputing:
      data = np.load('results/shap_LinearRegression.npz', allow_pickle=True)
      shap_vals = data['shap_values']; X_bg = data['X_background']; fn = data['feature_names'].tolist()
      display = ['\u9884\u7559SE' if x == '\u9884\u7559' else x for x in fn]  # 预留 -> 预留SE
      shap.summary_plot(shap_vals, pd.DataFrame(X_bg, columns=display), ...)
    """
    if not HAS_SHAP:
        return None
    # Y-tick label: 预留 -> 预留SE
    _yu = "\u9884\u7559"  # 预留
    display_names = ["\u9884\u7559SE" if f == _yu else f for f in feature_names]
    X_train = np.asarray(X_train)
    if len(X_train) > max_background:
        rng = np.random.default_rng(RANDOM_STATE)
        idx = rng.choice(len(X_train), size=max_background, replace=False)
        X_bg = X_train[idx]
    else:
        X_bg = X_train
    X_bg_df = pd.DataFrame(X_bg, columns=feature_names)
    X_bg_plot = pd.DataFrame(X_bg, columns=display_names)
    try:
        if model_name in ("RandomForest", "XGBoost"):
            explainer = shap.TreeExplainer(estimator, X_bg)
            shap_vals = explainer.shap_values(X_bg)
            if isinstance(shap_vals, list):
                shap_vals = shap_vals[0]
        elif model_name == "LinearRegression":
            masker = shap.maskers.Independent(X_bg)
            explainer = shap.LinearExplainer(estimator, masker)
            shap_vals = explainer.shap_values(X_bg)
        else:
            explainer = shap.KernelExplainer(estimator.predict, X_bg)
            shap_vals = explainer.shap_values(X_bg, nsamples=min(nsamples_kernel, len(X_bg) * 2))
        shap_vals = np.asarray(shap_vals)
        if shap_vals.ndim == 3:
            shap_vals = shap_vals[0]
        mean_abs = np.abs(shap_vals).mean(axis=0)
        order = np.argsort(-mean_abs)
        rows = []
        for r, j in enumerate(order):
            rows.append({
                "Model": model_name,
                "Feature": feature_names[j],
                "mean_abs_shap": float(mean_abs[j]),
                "rank": r + 1,
            })
        df_rank = pd.DataFrame(rows)

        res_dir = Path(res_dir)
        res_dir.mkdir(parents=True, exist_ok=True)

        # Save SHAP values and background to .npz for later replot without recomputing
        out_npz = res_dir / ("shap_%s%s.npz" % (prefix, model_name))
        np.savez_compressed(
            out_npz,
            shap_values=shap_vals,
            X_background=X_bg,
            feature_names=np.array(feature_names, dtype=object),
        )
        print("  Saved:", out_npz)

        # Plot with Chinese-safe font and display names (Reserved_SE for 预留)
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans", "Arial Unicode MS"]
        plt.rcParams["axes.unicode_minus"] = False
        # Summary (bar): mean |SHAP| per feature
        shap.summary_plot(shap_vals, X_bg_plot, plot_type="bar", show=False)
        out_bar = res_dir / ("shap_summary_%s%s.png" % (prefix, model_name))
        plt.gcf().savefig(out_bar, dpi=150, bbox_inches="tight")
        plt.close()
        print("  Saved:", out_bar)
        # Beeswarm (dot) plot
        shap.summary_plot(shap_vals, X_bg_plot, show=False)
        out_beeswarm = res_dir / ("shap_beeswarm_%s%s.png" % (prefix, model_name))
        plt.gcf().savefig(out_beeswarm, dpi=150, bbox_inches="tight")
        plt.close()
        print("  Saved:", out_beeswarm)
        return df_rank
    except Exception as e:
        print("  SHAP failed for %s: %s" % (model_name, e))
        return None


def load_shap_and_plot(npz_path, out_dir=None, dpi=150):
    """
    Load SHAP data from a .npz file (saved by compute_shap_ranking_and_plots) and
    regenerate summary (bar) and beeswarm plots. Use when you want to replot without
    recomputing SHAP.
    npz_path: path to shap_*ModelName.npz
    out_dir: directory to save pngs; default same as npz file directory.
    """
    if not HAS_SHAP:
        print("SHAP not installed. pip install shap")
        return
    npz_path = Path(npz_path)
    if not npz_path.exists():
        print("File not found:", npz_path)
        return
    out_dir = Path(out_dir) if out_dir else npz_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    data = np.load(npz_path, allow_pickle=True)
    shap_vals = data["shap_values"]
    X_bg = data["X_background"]
    feature_names = data["feature_names"].tolist()
    _yu = "\u9884\u7559"  # 预留
    display_names = ["\u9884\u7559SE" if f == _yu else f for f in feature_names]
    X_bg_plot = pd.DataFrame(X_bg, columns=display_names)
    # npz stem e.g. shap_LinearRegression or shap_formula_feat_LinearRegression
    suffix = npz_path.stem[5:] if npz_path.stem.startswith("shap_") else npz_path.stem
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False
    shap.summary_plot(shap_vals, X_bg_plot, plot_type="bar", show=False)
    out_bar = out_dir / ("shap_summary_%s.png" % suffix)
    plt.gcf().savefig(out_bar, dpi=dpi, bbox_inches="tight")
    plt.close()
    print("Saved:", out_bar)
    shap.summary_plot(shap_vals, X_bg_plot, show=False)
    out_beeswarm = out_dir / ("shap_beeswarm_%s.png" % suffix)
    plt.gcf().savefig(out_beeswarm, dpi=dpi, bbox_inches="tight")
    plt.close()
    print("Saved:", out_beeswarm)


def compute_metrics(y_true, y_pred):
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    mask = ~(np.isnan(y_true) | np.isnan(y_pred))
    y_true = y_true[mask]
    y_pred = y_pred[mask]
    if len(y_true) < 2:
        return {"n": len(y_true), "MAE": np.nan, "RMSE": np.nan, "MedAE": np.nan,
                "R2": np.nan, "pct_0.25": np.nan, "pct_0.5": np.nan, "pct_1": np.nan}
    return {
        "n": len(y_true),
        "MAE": mae(y_true, y_pred),
        "RMSE": rmse(y_true, y_pred),
        "MedAE": medae(y_true, y_pred),
        "R2": r2(y_true, y_pred),
        "pct_0.25": pct_within(y_true, y_pred, 0.25),
        "pct_0.5": pct_within(y_true, y_pred, 0.5),
        "pct_1": pct_within(y_true, y_pred, 1.0),
    }


def bootstrap_ci_mean(x, n_boot=5000, alpha=0.05, rng=None):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) == 0:
        return (np.nan, np.nan, np.nan)
    if rng is None:
        rng = np.random.default_rng(RANDOM_STATE)
    idx = rng.integers(0, len(x), size=(n_boot, len(x)))
    boot_means = x[idx].mean(axis=1)
    low = float(np.quantile(boot_means, alpha / 2))
    high = float(np.quantile(boot_means, 1 - alpha / 2))
    return (float(np.mean(x)), low, high)


def paired_bootstrap_ci_mean_diff(a, b, n_boot=5000, alpha=0.05, rng=None):
    """
    CI of mean(a - b) under paired bootstrap.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    mask = ~(np.isnan(a) | np.isnan(b))
    a = a[mask]
    b = b[mask]
    if len(a) == 0:
        return (np.nan, np.nan, np.nan)
    if rng is None:
        rng = np.random.default_rng(RANDOM_STATE)
    diff = a - b
    idx = rng.integers(0, len(diff), size=(n_boot, len(diff)))
    boot_means = diff[idx].mean(axis=1)
    low = float(np.quantile(boot_means, alpha / 2))
    high = float(np.quantile(boot_means, 1 - alpha / 2))
    return (float(np.mean(diff)), low, high)


def paired_permutation_test_mean_diff(a, b, n_perm=20000, rng=None):
    """
    Paired permutation (sign-flip) test for H0: mean(a - b) = 0.
    Returns two-sided p-value.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    mask = ~(np.isnan(a) | np.isnan(b))
    d = (a - b)[mask]
    if len(d) == 0:
        return np.nan
    if rng is None:
        rng = np.random.default_rng(RANDOM_STATE)
    obs = float(np.mean(d))
    signs = rng.choice(np.array([-1.0, 1.0]), size=(n_perm, len(d)))
    perm_means = (signs * d[None, :]).mean(axis=1)
    p = (np.sum(np.abs(perm_means) >= abs(obs)) + 1) / (n_perm + 1)
    return float(p)


def holm_adjust(pvals):
    """
    Holm-Bonferroni adjusted p-values.
    """
    pvals = np.asarray(pvals, dtype=float)
    n = len(pvals)
    out = np.full(n, np.nan, dtype=float)
    valid = ~np.isnan(pvals)
    if not np.any(valid):
        return out
    p = pvals[valid]
    m = len(p)
    order = np.argsort(p)
    p_sorted = p[order]
    adj_sorted = np.empty(m, dtype=float)
    for i in range(m):
        adj_sorted[i] = (m - i) * p_sorted[i]
    adj_sorted = np.maximum.accumulate(adj_sorted)
    adj_sorted = np.minimum(adj_sorted, 1.0)
    inv = np.empty(m, dtype=int)
    inv[order] = np.arange(m)
    out_valid = adj_sorted[inv]
    out[valid] = out_valid
    return out


def run_paired_inference_mae(y_true, pred_test_by_model, model_order, res_dir, prefix="ml_postSE"):
    """
    Compute:
      1) per-model MAE and bootstrap 95% CI;
      2) pairwise comparison vs best MAE model with paired bootstrap 95% CI and paired permutation p.
    Saves CSV files to results directory.
    """
    y_true = np.asarray(y_true, dtype=float)
    rng = np.random.default_rng(RANDOM_STATE)
    mae_rows = []
    ae_by_model = {}
    for name in model_order:
        if name not in pred_test_by_model:
            continue
        pred = np.asarray(pred_test_by_model[name], dtype=float)
        ae = np.abs(pred - y_true)
        ae = ae[~np.isnan(ae)]
        ae_by_model[name] = ae
        mae_mean, ci_low, ci_high = bootstrap_ci_mean(ae, n_boot=5000, alpha=0.05, rng=rng)
        mae_rows.append({
            "Model": name,
            "n_test": int(len(ae)),
            "MAE": float(mae_mean),
            "MAE_CI95_low": float(ci_low),
            "MAE_CI95_high": float(ci_high),
        })
    df_mae = pd.DataFrame(mae_rows).sort_values("MAE", ascending=True).reset_index(drop=True)
    if len(df_mae) == 0:
        return None, None

    out_mae = Path(res_dir) / ("%s_test_mae_ci.csv" % prefix)
    df_mae.to_csv(out_mae, index=False, encoding="utf-8")
    print("Saved:", out_mae)

    best_model = df_mae.iloc[0]["Model"]
    ae_best = ae_by_model[best_model]
    pair_rows = []
    pvals = []
    for _, r in df_mae.iterrows():
        name = r["Model"]
        if name == best_model:
            continue
        ae_m = ae_by_model[name]
        n_pair = min(len(ae_m), len(ae_best))
        if n_pair < 3:
            continue
        # In this script, test predictions are generated on identical test index,
        # so lengths are expected equal. Use explicit truncation for safety.
        ae_m = ae_m[:n_pair]
        ae_b = ae_best[:n_pair]
        mean_diff, ci_low, ci_high = paired_bootstrap_ci_mean_diff(ae_m, ae_b, n_boot=5000, alpha=0.05, rng=rng)
        p = paired_permutation_test_mean_diff(ae_m, ae_b, n_perm=20000, rng=rng)
        pvals.append(p)
        pair_rows.append({
            "Best_model": best_model,
            "Compared_model": name,
            "n_pair": int(n_pair),
            "MAE_diff_compared_minus_best": float(mean_diff),
            "MAE_diff_CI95_low": float(ci_low),
            "MAE_diff_CI95_high": float(ci_high),
            "p_value_paired_permutation": float(p),
        })
    df_pair = pd.DataFrame(pair_rows)
    if len(df_pair) > 0:
        df_pair["p_value_holm"] = holm_adjust(df_pair["p_value_paired_permutation"].values)
        out_pair = Path(res_dir) / ("%s_test_pairwise_vs_best.csv" % prefix)
        df_pair.to_csv(out_pair, index=False, encoding="utf-8")
        print("Saved:", out_pair)
    else:
        out_pair = None

    return df_mae, df_pair


def _assign_al_subgroup(al_series):
    """Assign AL subgroup: 26-28mm, 28-30mm, >=30mm. Returns array of str or NaN."""
    al = pd.to_numeric(al_series, errors="coerce")
    out = pd.Series(index=al.index, dtype=object)
    out[(al >= 26) & (al < 28)] = "26-28mm"
    out[(al >= 28) & (al < 30)] = "28-30mm"
    out[al >= 30] = ">=30mm"
    return out


def _assign_k_subgroup(k_avg_series):
    """Assign K subgroup: K<40D, 40-46D, >=46D. Returns array of str or NaN."""
    k = pd.to_numeric(k_avg_series, errors="coerce")
    out = pd.Series(index=k.index, dtype=object)
    out[k < 40] = "K<40D"
    out[(k >= 40) & (k < 46)] = "40-46D"
    out[k >= 46] = ">=46D"
    return out


def _plot_save(out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print("Saved:", out_path)


def main():
    parser = argparse.ArgumentParser(description="ML models: predict 术后SE, stratified by cataract type.")
    parser.add_argument("-i", "--input", type=str, default=None, help="Input Excel path")
    parser.add_argument("-o", "--output", type=str, default=None, help="Output CSV for metrics")
    parser.add_argument("--save-models", action="store_true", help="Save fitted models to results/")
    parser.add_argument("--no-plots", action="store_true", help="Skip generating plots")
    parser.add_argument("--no-shap", action="store_true", help="Skip SHAP feature ranking")
    parser.add_argument("--plot-shap", type=str, default=None, metavar="NPZ",
                        help="Replot SHAP from saved .npz (e.g. results/shap_LinearRegression.npz) and exit")
    args = parser.parse_args()

    if args.plot_shap:
        load_shap_and_plot(args.plot_shap)
        return

    in_path = Path(args.input) if args.input else DEFAULT_INPUT
    if not in_path.is_absolute():
        in_path = BASE / in_path
    if not in_path.exists():
        print("Input not found:", in_path)
        return

    out_path = Path(args.output) if args.output else BASE / "results" / "ml_postSE_comparison.csv"
    if not out_path.is_absolute():
        out_path = BASE / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    res_dir = BASE / "results"

    df = pd.read_excel(in_path, sheet_name=0)
    feat_cols = [c for c in FEAT_NAMES if c in df.columns]
    if not feat_cols or TARGET_NAME not in df.columns:
        print("Missing feature or target. Need", TARGET_NAME, "and at least one of", FEAT_NAMES)
        return

    X_raw = df[feat_cols].apply(_to_numeric)
    y_all = _to_numeric(df[TARGET_NAME])
    valid = ~y_all.isna()
    # Unify cataract type: merge "高度近视白内障" and "高度近视" into one group "高度近视"
    if CAT_TYPE_COL not in df.columns:
        stratum = pd.Series("Overall", index=df.index)
    else:
        stratum = df[CAT_TYPE_COL].astype(str).fillna("(missing)")
        stratum = stratum.str.strip().replace("", "(missing)")
        stratum = stratum.replace("高度近视白内障", "高度近视")
    stratum_valid = stratum.loc[valid].copy()

    X_valid = X_raw.loc[valid]
    y_valid = y_all.loc[valid]
    if len(y_valid) < 50:
        print("Too few rows with non-NA 术后SE:", len(y_valid))
        return

    # Stratified split by cataract type
    strata_counts = stratum_valid.value_counts()
    stratify_labels = stratum_valid.values
    try:
        i_train, i_test = train_test_split(
            np.arange(len(y_valid)),
            test_size=TEST_SIZE,
            random_state=RANDOM_STATE,
            stratify=stratify_labels,
        )
    except ValueError:
        i_train, i_test = train_test_split(
            np.arange(len(y_valid)),
            test_size=TEST_SIZE,
            random_state=RANDOM_STATE,
        )
        print("Stratified split failed (e.g. rare strata), using random split.")

    train_idx = y_valid.index[i_train]
    test_idx = y_valid.index[i_test]
    X_train = X_valid.loc[train_idx]
    X_test = X_valid.loc[test_idx]
    y_train = y_valid.loc[train_idx]
    y_test = y_valid.loc[test_idx]
    stratum_test = stratum_valid.loc[test_idx].values

    imputer = SimpleImputer(strategy="median")
    X_train_imp = imputer.fit_transform(X_train)
    X_test_imp = imputer.transform(X_test)
    X_train_imp = pd.DataFrame(X_train_imp, columns=feat_cols, index=train_idx)
    X_test_imp = pd.DataFrame(X_test_imp, columns=feat_cols, index=test_idx)

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train_imp)
    X_test_s = scaler.transform(X_test_imp)

    models = {
        "LinearRegression": LinearRegression(),
        "SVR": SVR(kernel="rbf", C=10.0, epsilon=0.1),
        "RandomForest": RandomForestRegressor(n_estimators=100, max_depth=10, random_state=RANDOM_STATE),
        "MLP": MLPRegressor(hidden_layer_sizes=(64, 32), max_iter=500, random_state=RANDOM_STATE),
    }
    if HAS_XGB:
        models["XGBoost"] = xgb.XGBRegressor(n_estimators=100, max_depth=6, random_state=RANDOM_STATE)

    use_scaled = ["LinearRegression", "SVR", "MLP"]
    fitted = {}
    pred_test_by_model = {}
    rows = []

    print("\n--- ML models: predict 术后SE (stratified split by", CAT_TYPE_COL, ") ---\n")
    print("Features:", feat_cols)
    print("Train n =", len(y_train), ", Test n =", len(y_test), "\n")

    for name, est in models.items():
        if name in use_scaled:
            X_tr, X_te = X_train_s, X_test_s
        else:
            X_tr, X_te = X_train_imp.values, X_test_imp.values
        est.fit(X_tr, y_train)
        pred_train = est.predict(X_tr)
        pred_test = est.predict(X_te)
        fitted[name] = est
        pred_test_by_model[name] = pred_test

        mt = compute_metrics(y_train, pred_train)
        rows.append({
            "Model": name, "Split": "Train", "Stratum": "Overall", "n": mt["n"],
            "MAE": mt["MAE"], "RMSE": mt["RMSE"], "MedAE": mt["MedAE"], "R2": mt["R2"],
            "pct_within_0.25": mt["pct_0.25"], "pct_within_0.5": mt["pct_0.5"], "pct_within_1": mt["pct_1"],
        })

        # Test overall
        me = compute_metrics(y_test, pred_test)
        rows.append({
            "Model": name, "Split": "Test", "Stratum": "Overall", "n": me["n"],
            "MAE": me["MAE"], "RMSE": me["RMSE"], "MedAE": me["MedAE"], "R2": me["R2"],
            "pct_within_0.25": me["pct_0.25"], "pct_within_0.5": me["pct_0.5"], "pct_within_1": me["pct_1"],
        })

        # Test by cataract type
        for st in np.unique(stratum_test):
            mask = stratum_test == st
            if np.sum(mask) < 2:
                continue
            me_st = compute_metrics(y_test.values[mask], pred_test[mask])
            rows.append({
                "Model": name, "Split": "Test", "Stratum": st, "n": me_st["n"],
                "MAE": me_st["MAE"], "RMSE": me_st["RMSE"], "MedAE": me_st["MedAE"], "R2": me_st["R2"],
                "pct_within_0.25": me_st["pct_0.25"], "pct_within_0.5": me_st["pct_0.5"], "pct_within_1": me_st["pct_1"],
            })

        print(name)
        print("  Train: MAE =", round(mt["MAE"], 4), " RMSE =", round(mt["RMSE"], 4), " R2 =", round(mt["R2"], 4),
              " | +/-0.25 D:", round(mt["pct_0.25"], 1), "% +/-0.5 D:", round(mt["pct_0.5"], 1), "% +/-1 D:", round(mt["pct_1"], 1), "%")
        print("  Test (overall): MAE =", round(me["MAE"], 4), " RMSE =", round(me["RMSE"], 4), " R2 =", round(me["R2"], 4),
              " | +/-0.25 D:", round(me["pct_0.25"], 1), "% +/-0.5 D:", round(me["pct_0.5"], 1), "% +/-1 D:", round(me["pct_1"], 1), "%")
        for st in np.unique(stratum_test):
            mask = stratum_test == st
            if np.sum(mask) < 2:
                continue
            me_st = compute_metrics(y_test.values[mask], pred_test[mask])
            print("  Test (", st, "): n =", me_st["n"], " MAE =", round(me_st["MAE"], 4), " RMSE =", round(me_st["RMSE"], 4),
                  " | +/-0.5 D:", round(me_st["pct_0.5"], 1), "%")
        print()

    result_df = pd.DataFrame(rows)
    result_df.to_csv(out_path, index=False, encoding="gb2312")
    print("Saved:", out_path)
    # Statistical inference for model comparison on test set:
    # MAE 95% CI (bootstrap) + paired permutation test vs best model.
    run_paired_inference_mae(
        y_true=y_test.values,
        pred_test_by_model=pred_test_by_model,
        model_order=list(models.keys()),
        res_dir=res_dir,
        prefix="ml_postSE",
    )

    # --- Subgroup analysis: Test set performance by AL and by K (same cutpoints as R script) ---
    if "AL" in feat_cols and len(pred_test_by_model) > 0:
        X_te = X_test_imp.copy()
        al_ser = X_te["AL"] if "AL" in X_te.columns else None
        if al_ser is not None:
            al_sub = _assign_al_subgroup(al_ser)
            y_te = y_test.values
            rows_al = []
            for sg in AL_LEVELS:
                mask = (al_sub == sg).values
                if np.sum(mask) < MIN_SUBGROUP_SIZE:
                    continue
                y_sg = y_te[mask]
                for name, pred in pred_test_by_model.items():
                    pred_sg = pred[mask]
                    m = compute_metrics(y_sg, pred_sg)
                    if m["n"] >= MIN_SUBGROUP_SIZE:
                        rows_al.append({
                            "Subgroup_type": "AL", "Stratum": sg, "Model": name,
                            "n": m["n"], "MAE": round(m["MAE"], 4), "RMSE": round(m["RMSE"], 4), "MedAE": round(m["MedAE"], 4),
                            "pct_within_0.25": round(m["pct_0.25"], 2), "pct_within_0.5": round(m["pct_0.5"], 2), "pct_within_1": round(m["pct_1"], 2),
                        })
            if rows_al:
                df_al = pd.DataFrame(rows_al)
                out_al = res_dir / "ml_postSE_test_by_AL_subgroup.csv"
                df_al.to_csv(out_al, index=False, encoding="utf-8")
                print("\nSaved (AL subgroup, test set):", out_al)
                for sg in AL_LEVELS:
                    sub = df_al[df_al["Stratum"] == sg]
                    if len(sub) > 0:
                        print("  ", sg, "n =", sub["n"].iloc[0], "models:", list(sub["Model"].unique()))

        k_avg_ser = None
        if "K1" in X_te.columns and "K2" in X_te.columns:
            k_avg_ser = (pd.to_numeric(X_te["K1"], errors="coerce") + pd.to_numeric(X_te["K2"], errors="coerce")) / 2
        elif "K_avg" in X_te.columns:
            k_avg_ser = pd.to_numeric(X_te["K_avg"], errors="coerce")
        if k_avg_ser is not None and k_avg_ser.notna().any():
            k_sub = _assign_k_subgroup(k_avg_ser)
            y_te = y_test.values
            rows_k = []
            for sg in K_LEVELS:
                mask = (k_sub == sg).values
                if np.sum(mask) < MIN_SUBGROUP_SIZE:
                    continue
                y_sg = y_te[mask]
                for name, pred in pred_test_by_model.items():
                    pred_sg = pred[mask]
                    m = compute_metrics(y_sg, pred_sg)
                    if m["n"] >= MIN_SUBGROUP_SIZE:
                        rows_k.append({
                            "Subgroup_type": "K", "Stratum": sg, "Model": name,
                            "n": m["n"], "MAE": round(m["MAE"], 4), "RMSE": round(m["RMSE"], 4), "MedAE": round(m["MedAE"], 4),
                            "pct_within_0.25": round(m["pct_0.25"], 2), "pct_within_0.5": round(m["pct_0.5"], 2), "pct_within_1": round(m["pct_1"], 2),
                        })
            if rows_k:
                df_k = pd.DataFrame(rows_k)
                out_k = res_dir / "ml_postSE_test_by_K_subgroup.csv"
                df_k.to_csv(out_k, index=False, encoding="utf-8")
                print("Saved (K subgroup, test set):", out_k)
    else:
        print("\nSkip ML subgroup analysis: AL not in features or no test predictions.")

    # SHAP feature ranking + summary & beeswarm plots (biometry-only models)
    if HAS_SHAP and not args.no_shap and fitted:
        print("\n--- SHAP feature ranking and plots (biometry) ---")
        shap_biometry_rows = []
        for name in fitted:
            X_tr = X_train_s if name in use_scaled else X_train_imp.values
            df_rank = compute_shap_ranking_and_plots(
                fitted[name], X_tr, feat_cols, name, res_dir, prefix=""
            )
            if df_rank is not None:
                shap_biometry_rows.append(df_rank)
                print("  %s: top 3 features" % name, list(df_rank.head(3)["Feature"].values))
        if shap_biometry_rows:
            shap_biometry_df = pd.concat(shap_biometry_rows, ignore_index=True)
            out_shap_b = res_dir / "shap_ranking_biometry.csv"
            shap_biometry_df.to_csv(out_shap_b, index=False, encoding="utf-8")
            print("Saved:", out_shap_b)

    # Build test set long-form for plots: 术后SE, Stratum, Model, Predicted
    test_records = []
    for i, idx in enumerate(test_idx):
        rec = {"术后SE": y_test.loc[idx], "Stratum": stratum_test[i]}
        for name, pred in pred_test_by_model.items():
            rec["Model"] = name
            rec["Predicted"] = pred[i]
            test_records.append(rec.copy())
    test_long = pd.DataFrame(test_records)
    test_metrics = result_df[(result_df["Split"] == "Test")].copy()

    # Plots
    if not args.no_plots:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            plt.rcParams["font.sans-serif"] = ["SimHei", "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
        except Exception:
            pass

        # 1. Scatter: Actual vs Predicted, one subplot per model, colored by Stratum
        n_models = len(models)
        ncol = min(3, n_models)
        nrow = (n_models + ncol - 1) // ncol
        fig, axes = plt.subplots(nrow, ncol, figsize=(4 * ncol, 4 * nrow))
        if n_models == 1:
            axes = np.array([axes])
        axes = axes.flatten()
        for k, (name, ax) in enumerate(zip(models.keys(), axes)):
            sub = test_long[test_long["Model"] == name]
            for st in sub["Stratum"].unique():
                s = sub[sub["Stratum"] == st]
                ax.scatter(s["术后SE"], s["Predicted"], label=st, alpha=0.65, s=20)
            ax.plot([sub["术后SE"].min(), sub["术后SE"].max()], [sub["术后SE"].min(), sub["术后SE"].max()], "k--", lw=1, label="y=x")
            ax.set_xlabel("Actual 术后SE (D)")
            ax.set_ylabel("Predicted (D)")
            ax.set_title(name)
            ax.legend(loc="best", fontsize=8)
            ax.grid(True, alpha=0.3)
        for k in range(n_models, len(axes)):
            axes[k].set_visible(False)
        fig.suptitle("ML: Predicted vs Actual 术后SE (test set)")
        plt.tight_layout()
        _plot_save(res_dir / "ml_actual_vs_predicted_scatter.png")

        # 2. Bar: MAE by Model and Stratum (Test only)
        plot_metrics = test_metrics[test_metrics["n"] >= 2].copy()
        model_names = list(models.keys())
        strata_uniq = sorted(plot_metrics["Stratum"].unique(), key=lambda s: (0 if s == "Overall" else 1, s)) if len(plot_metrics) > 0 else []
        if len(plot_metrics) > 0 and len(strata_uniq) > 0:
            fig, ax = plt.subplots(figsize=(10, 5))
            x = np.arange(len(model_names))
            width = 0.8 / max(len(strata_uniq), 1)
            for i, st in enumerate(strata_uniq):
                sub = plot_metrics[plot_metrics["Stratum"] == st]
                mae_vals = [sub[sub["Model"] == m]["MAE"].values[0] if len(sub[sub["Model"] == m]) else np.nan for m in model_names]
                off = (i - len(strata_uniq) / 2) * width + width / 2
                ax.bar(x + off, mae_vals, width, label=st)
            ax.set_xticks(x)
            ax.set_xticklabels(model_names, rotation=25, ha="right")
            ax.set_ylabel("MAE (D)")
            ax.set_title("Test: MAE by Model and Cataract Type")
            ax.legend(loc="best", fontsize=8)
            ax.grid(True, axis="y", alpha=0.3)
            plt.tight_layout()
            _plot_save(res_dir / "ml_MAE_by_stratum.png")

        # 3. Bar: % within +/-0.5 D by Model and Stratum
        if len(plot_metrics) > 0 and len(strata_uniq) > 0:
            fig, ax = plt.subplots(figsize=(10, 5))
            for i, st in enumerate(strata_uniq):
                sub = plot_metrics[plot_metrics["Stratum"] == st]
                pct_vals = [sub[sub["Model"] == m]["pct_within_0.5"].values[0] if len(sub[sub["Model"] == m]) else np.nan for m in model_names]
                off = (i - len(strata_uniq) / 2) * width + width / 2
                ax.bar(x + off, pct_vals, width, label=st)
            ax.set_xticks(x)
            ax.set_xticklabels(model_names, rotation=25, ha="right")
            ax.set_ylabel("% within +/-0.5 D")
            ax.set_title("Test: % within +/-0.5 D by Model and Cataract Type")
            ax.axhline(50, color="gray", linestyle=":", lw=1)
            ax.axhline(75, color="gray", linestyle=":", lw=1)
            ax.axhline(90, color="gray", linestyle=":", lw=1)
            ax.set_ylim(0, 100)
            ax.legend(loc="best", fontsize=8)
            ax.grid(True, axis="y", alpha=0.3)
            plt.tight_layout()
            _plot_save(res_dir / "ml_pct_within_0.5_by_stratum.png")

        # 4. Bland-Altman: (Pred - Actual) vs mean, one subplot per model
        test_long["Mean"] = (test_long["术后SE"] + test_long["Predicted"]) / 2
        test_long["Diff"] = test_long["Predicted"] - test_long["术后SE"]
        fig, axes = plt.subplots(nrow, ncol, figsize=(4 * ncol, 4 * nrow))
        axes = np.atleast_1d(axes).flatten()
        for k, name in enumerate(models.keys()):
            sub = test_long[test_long["Model"] == name]
            for st in sub["Stratum"].unique():
                s = sub[sub["Stratum"] == st]
                axes[k].scatter(s["Mean"], s["Diff"], label=st, alpha=0.6, s=18)
            m = sub["Diff"].mean()
            sd = sub["Diff"].std()
            axes[k].axhline(m, color="darkred", linestyle="-", lw=1)
            axes[k].axhline(m - 1.96 * sd, color="gray", linestyle="--", lw=0.8)
            axes[k].axhline(m + 1.96 * sd, color="gray", linestyle="--", lw=0.8)
            axes[k].set_xlabel("Mean (Actual, Predicted) (D)")
            axes[k].set_ylabel("Predicted - Actual (D)")
            axes[k].set_title(name)
            axes[k].legend(loc="best", fontsize=8)
            axes[k].grid(True, alpha=0.3)
        for k in range(n_models, len(axes)):
            axes[k].set_visible(False)
        fig.suptitle("ML: Bland-Altman (test set)")
        plt.tight_layout()
        _plot_save(res_dir / "ml_bland_altman.png")

        # 5. Boxplot: Prediction error by Model and Stratum
        fig, ax = plt.subplots(figsize=(10, 5))
        model_order = list(models.keys())
        strata_plot = sorted(test_long["Stratum"].unique(), key=lambda s: (0 if s == "Overall" else 1, s))
        n_strata = len(strata_plot)
        w = 0.8 / max(n_strata, 1)
        positions = []
        data_list = []
        for j, name in enumerate(model_order):
            sub = test_long[test_long["Model"] == name]
            for i, st in enumerate(strata_plot):
                s = sub[sub["Stratum"] == st]["Diff"]
                if len(s) == 0:
                    s = [np.nan]
                pos = j + (i - n_strata / 2) * w + w / 2
                positions.append(pos)
                data_list.append(s)
        ax.boxplot(data_list, positions=positions, widths=w * 0.8, patch_artist=True, showfliers=True)
        ax.axhline(0, color="gray", linestyle="--", lw=1)
        ax.set_xticks(range(len(model_order)))
        ax.set_xticklabels(model_order, rotation=25, ha="right")
        ax.set_ylabel("Prediction error (D)")
        ax.set_title("Test: Prediction Error by Model and Cataract Type")
        ax.grid(True, axis="y", alpha=0.3)
        if n_strata <= 8:
            from matplotlib.patches import Patch
            legend_elements = [Patch(facecolor="C%d" % i, label=st) for i, st in enumerate(strata_plot)]
            ax.legend(handles=legend_elements, loc="best", fontsize=8)
        plt.tight_layout()
        _plot_save(res_dir / "ml_error_boxplot.png")

    if args.save_models:
        import joblib
        joblib.dump(
            {"imputer": imputer, "scaler": scaler, "models": fitted, "feat_cols": feat_cols},
            res_dir / "ml_postSE_pipeline.joblib",
        )
        print("Saved pipeline to results/ml_postSE_pipeline.joblib")

    # --- Formula-as-feature: add SRKT, Holladay1, Haigis predicted SE as input features; full analysis ---
    FORMULA_FEAT_COLS = ["SRKT_SE_pred_actualIOL", "Holladay1_SE_pred_actualIOL", "Haigis_SE_pred_actualIOL"]
    result_ff = None
    if all(c in df.columns for c in FORMULA_FEAT_COLS):
        valid_ff = valid.copy()
        for c in FORMULA_FEAT_COLS:
            valid_ff &= df[c].notna()
        df_ff = df.loc[valid_ff].copy()
        y_ff = _to_numeric(df_ff[TARGET_NAME])
        df_ff = df_ff[~y_ff.isna()]
        y_ff = y_ff.loc[df_ff.index]
        if len(df_ff) < 50:
            print("\nFormula-as-feature: too few rows (n=%d). Skip.\n" % len(df_ff))
        else:
            feat_cols_ff = [c for c in FEAT_NAMES if c in df_ff.columns] + [c for c in FORMULA_FEAT_COLS if c in df_ff.columns]
            X_ff = df_ff[feat_cols_ff].apply(_to_numeric)
            stratum_ff = stratum.loc[df_ff.index].copy()
            try:
                i_tr_ff, i_te_ff = train_test_split(np.arange(len(y_ff)), test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=stratum_ff.values)
            except Exception:
                i_tr_ff, i_te_ff = train_test_split(np.arange(len(y_ff)), test_size=TEST_SIZE, random_state=RANDOM_STATE)
            train_idx_ff = df_ff.index[i_tr_ff]
            test_idx_ff = df_ff.index[i_te_ff]
            X_train_ff = X_ff.loc[train_idx_ff]
            X_test_ff = X_ff.loc[test_idx_ff]
            y_train_ff = y_ff.loc[train_idx_ff]
            y_test_ff = y_ff.loc[test_idx_ff]
            stratum_test_ff = stratum_ff.loc[test_idx_ff].values

            imp_ff = SimpleImputer(strategy="median")
            X_train_ff_imp = pd.DataFrame(imp_ff.fit_transform(X_train_ff), columns=feat_cols_ff, index=train_idx_ff)
            X_test_ff_imp = pd.DataFrame(imp_ff.transform(X_test_ff), columns=feat_cols_ff, index=test_idx_ff)
            scaler_ff = StandardScaler()
            X_train_ff_s = scaler_ff.fit_transform(X_train_ff_imp)
            X_test_ff_s = scaler_ff.transform(X_test_ff_imp)

            models_ff = {
                "LinearRegression": LinearRegression(),
                "SVR": SVR(kernel="rbf", C=10.0, epsilon=0.1),
                "RandomForest": RandomForestRegressor(n_estimators=100, max_depth=10, random_state=RANDOM_STATE),
                "MLP": MLPRegressor(hidden_layer_sizes=(64, 32), max_iter=500, random_state=RANDOM_STATE),
            }
            if HAS_XGB:
                models_ff["XGBoost"] = xgb.XGBRegressor(n_estimators=100, max_depth=6, random_state=RANDOM_STATE)

            rows_ff = []
            pred_test_ff = {}
            fitted_ff = {}
            print("\n--- Formula-as-feature (SRKT, Holladay1, Haigis pred): n = %d (train %d, test %d) ---\n" % (len(df_ff), len(y_train_ff), len(y_test_ff)))
            print("Features:", feat_cols_ff)
            for name, est in models_ff.items():
                X_tr = X_train_ff_s if name in use_scaled else X_train_ff_imp.values
                X_te = X_test_ff_s if name in use_scaled else X_test_ff_imp.values
                est.fit(X_tr, y_train_ff)
                fitted_ff[name] = est
                pred_te = est.predict(X_te)
                pred_test_ff[name] = pred_te
                mt = compute_metrics(y_train_ff, est.predict(X_tr))
                me = compute_metrics(y_test_ff, pred_te)
                rows_ff.append({"Model": name, "Split": "Train", "Stratum": "Overall", "n": mt["n"], "MAE": mt["MAE"], "RMSE": mt["RMSE"], "MedAE": mt["MedAE"], "R2": mt["R2"], "pct_within_0.25": mt["pct_0.25"], "pct_within_0.5": mt["pct_0.5"], "pct_within_1": mt["pct_1"]})
                rows_ff.append({"Model": name, "Split": "Test", "Stratum": "Overall", "n": me["n"], "MAE": me["MAE"], "RMSE": me["RMSE"], "MedAE": me["MedAE"], "R2": me["R2"], "pct_within_0.25": me["pct_0.25"], "pct_within_0.5": me["pct_0.5"], "pct_within_1": me["pct_1"]})
                for st in np.unique(stratum_test_ff):
                    msk = stratum_test_ff == st
                    if np.sum(msk) < 2:
                        continue
                    me_st = compute_metrics(y_test_ff.values[msk], pred_te[msk])
                    rows_ff.append({"Model": name, "Split": "Test", "Stratum": st, "n": me_st["n"], "MAE": me_st["MAE"], "RMSE": me_st["RMSE"], "MedAE": me_st["MedAE"], "R2": me_st["R2"], "pct_within_0.25": me_st["pct_0.25"], "pct_within_0.5": me_st["pct_0.5"], "pct_within_1": me_st["pct_1"]})
                print(name, " Test MAE =", round(me["MAE"], 4), " R2 =", round(me["R2"], 4), " | +/-0.5 D:", round(me["pct_0.5"], 1), "%")

            result_ff = pd.DataFrame(rows_ff)
            out_ff = res_dir / "ml_postSE_comparison_formula_feat.csv"
            result_ff.to_csv(out_ff, index=False, encoding="gb2312")
            print("Saved:", out_ff)
            run_paired_inference_mae(
                y_true=y_test_ff.values,
                pred_test_by_model=pred_test_ff,
                model_order=list(models_ff.keys()),
                res_dir=res_dir,
                prefix="ml_postSE_formula_feat",
            )

            if HAS_SHAP and not args.no_shap and fitted_ff:
                print("\n--- SHAP feature ranking and plots (formula-as-feature) ---")
                shap_ff_rows = []
                for name in fitted_ff:
                    X_tr = X_train_ff_s if name in use_scaled else X_train_ff_imp.values
                    df_rank = compute_shap_ranking_and_plots(
                        fitted_ff[name], X_tr, feat_cols_ff, name, res_dir, prefix="formula_feat_"
                    )
                    if df_rank is not None:
                        shap_ff_rows.append(df_rank)
                        print("  %s: top 3 features" % name, list(df_rank.head(3)["Feature"].values))
                if shap_ff_rows:
                    shap_ff_df = pd.concat(shap_ff_rows, ignore_index=True)
                    out_shap_ff = res_dir / "shap_ranking_formula_feat.csv"
                    shap_ff_df.to_csv(out_shap_ff, index=False, encoding="utf-8")
                    print("Saved:", out_shap_ff)

            test_records_ff = []
            for i, idx in enumerate(test_idx_ff):
                rec = {"术后SE": y_test_ff.loc[idx], "Stratum": stratum_test_ff[i]}
                for n, pred in pred_test_ff.items():
                    rec["Model"] = n
                    rec["Predicted"] = pred[i]
                    test_records_ff.append(rec.copy())
            test_long_ff = pd.DataFrame(test_records_ff)
            test_long_ff["Mean"] = (test_long_ff["术后SE"] + test_long_ff["Predicted"]) / 2
            test_long_ff["Diff"] = test_long_ff["Predicted"] - test_long_ff["术后SE"]
            test_metrics_ff = result_ff[result_ff["Split"] == "Test"].copy()

            if not args.no_plots:
                n_models_ff = len(models_ff)
                ncol_ff = min(3, n_models_ff)
                nrow_ff = (n_models_ff + ncol_ff - 1) // ncol_ff
                fig, axes = plt.subplots(nrow_ff, ncol_ff, figsize=(4 * ncol_ff, 4 * nrow_ff))
                axes = np.atleast_1d(axes).flatten()
                for k, (name, ax) in enumerate(zip(models_ff.keys(), axes)):
                    sub = test_long_ff[test_long_ff["Model"] == name]
                    for st in sub["Stratum"].unique():
                        s = sub[sub["Stratum"] == st]
                        ax.scatter(s["术后SE"], s["Predicted"], label=st, alpha=0.65, s=20)
                    ax.plot([sub["术后SE"].min(), sub["术后SE"].max()], [sub["术后SE"].min(), sub["术后SE"].max()], "k--", lw=1)
                    ax.set_xlabel("Actual 术后SE (D)")
                    ax.set_ylabel("Predicted (D)")
                    ax.set_title(name)
                    ax.legend(loc="best", fontsize=8)
                    ax.grid(True, alpha=0.3)
                for k in range(n_models_ff, len(axes)):
                    axes[k].set_visible(False)
                fig.suptitle("ML Formula-as-feature: Predicted vs Actual (test)")
                plt.tight_layout()
                _plot_save(res_dir / "ml_formula_feat_actual_vs_predicted_scatter.png")

                plot_ff = test_metrics_ff[test_metrics_ff["n"] >= 2]
                strata_ff_uniq = sorted(plot_ff["Stratum"].unique(), key=lambda s: (0 if s == "Overall" else 1, s)) if len(plot_ff) > 0 else []
                if len(plot_ff) > 0 and len(strata_ff_uniq) > 0:
                    model_names_ff = list(models_ff.keys())
                    x_ff = np.arange(len(model_names_ff))
                    width_ff = 0.8 / max(len(strata_ff_uniq), 1)
                    fig, ax = plt.subplots(figsize=(10, 5))
                    for i, st in enumerate(strata_ff_uniq):
                        sub = plot_ff[plot_ff["Stratum"] == st]
                        mae_vals = [sub[sub["Model"] == m]["MAE"].values[0] if len(sub[sub["Model"] == m]) else np.nan for m in model_names_ff]
                        off = (i - len(strata_ff_uniq) / 2) * width_ff + width_ff / 2
                        ax.bar(x_ff + off, mae_vals, width_ff, label=st)
                    ax.set_xticks(x_ff)
                    ax.set_xticklabels(model_names_ff, rotation=25, ha="right")
                    ax.set_ylabel("MAE (D)")
                    ax.set_title("Formula-as-feature: Test MAE by Model and Cataract Type")
                    ax.legend(loc="best", fontsize=8)
                    ax.grid(True, axis="y", alpha=0.3)
                    plt.tight_layout()
                    _plot_save(res_dir / "ml_formula_feat_MAE_by_stratum.png")

                    fig, ax = plt.subplots(figsize=(10, 5))
                    for i, st in enumerate(strata_ff_uniq):
                        sub = plot_ff[plot_ff["Stratum"] == st]
                        pct_vals = [sub[sub["Model"] == m]["pct_within_0.5"].values[0] if len(sub[sub["Model"] == m]) else np.nan for m in model_names_ff]
                        off = (i - len(strata_ff_uniq) / 2) * width_ff + width_ff / 2
                        ax.bar(x_ff + off, pct_vals, width_ff, label=st)
                    ax.set_xticks(x_ff)
                    ax.set_xticklabels(model_names_ff, rotation=25, ha="right")
                    ax.set_ylabel("% within +/-0.5 D")
                    ax.set_title("Formula-as-feature: % within +/-0.5 D by Model and Cataract Type")
                    ax.axhline(50, color="gray", linestyle=":", lw=1)
                    ax.axhline(75, color="gray", linestyle=":", lw=1)
                    ax.axhline(90, color="gray", linestyle=":", lw=1)
                    ax.set_ylim(0, 100)
                    ax.legend(loc="best", fontsize=8)
                    ax.grid(True, axis="y", alpha=0.3)
                    plt.tight_layout()
                    _plot_save(res_dir / "ml_formula_feat_pct_within_0.5_by_stratum.png")

                fig, axes = plt.subplots(nrow_ff, ncol_ff, figsize=(4 * ncol_ff, 4 * nrow_ff))
                axes = np.atleast_1d(axes).flatten()
                for k, name in enumerate(models_ff.keys()):
                    sub = test_long_ff[test_long_ff["Model"] == name]
                    for st in sub["Stratum"].unique():
                        s = sub[sub["Stratum"] == st]
                        axes[k].scatter(s["Mean"], s["Diff"], label=st, alpha=0.6, s=18)
                    m, sd = sub["Diff"].mean(), sub["Diff"].std()
                    axes[k].axhline(m, color="darkred", linestyle="-", lw=1)
                    axes[k].axhline(m - 1.96 * sd, color="gray", linestyle="--", lw=0.8)
                    axes[k].axhline(m + 1.96 * sd, color="gray", linestyle="--", lw=0.8)
                    axes[k].set_xlabel("Mean (Actual, Predicted) (D)")
                    axes[k].set_ylabel("Predicted - Actual (D)")
                    axes[k].set_title(name)
                    axes[k].legend(loc="best", fontsize=8)
                    axes[k].grid(True, alpha=0.3)
                for k in range(n_models_ff, len(axes)):
                    axes[k].set_visible(False)
                fig.suptitle("ML Formula-as-feature: Bland-Altman (test)")
                plt.tight_layout()
                _plot_save(res_dir / "ml_formula_feat_bland_altman.png")

                strata_plot_ff = sorted(test_long_ff["Stratum"].unique(), key=lambda s: (0 if s == "Overall" else 1, s))
                n_strata_ff = len(strata_plot_ff)
                w_ff = 0.8 / max(n_strata_ff, 1)
                positions_ff, data_list_ff = [], []
                for j, name in enumerate(models_ff.keys()):
                    sub = test_long_ff[test_long_ff["Model"] == name]
                    for i, st in enumerate(strata_plot_ff):
                        s = sub[sub["Stratum"] == st]["Diff"]
                        positions_ff.append(j + (i - n_strata_ff / 2) * w_ff + w_ff / 2)
                        data_list_ff.append(s if len(s) > 0 else [np.nan])
                fig, ax = plt.subplots(figsize=(10, 5))
                ax.boxplot(data_list_ff, positions=positions_ff, widths=w_ff * 0.8, patch_artist=True, showfliers=True)
                ax.axhline(0, color="gray", linestyle="--", lw=1)
                ax.set_xticks(range(len(models_ff)))
                ax.set_xticklabels(list(models_ff.keys()), rotation=25, ha="right")
                ax.set_ylabel("Prediction error (D)")
                ax.set_title("Formula-as-feature: Prediction Error by Model and Cataract Type")
                ax.grid(True, axis="y", alpha=0.3)
                if n_strata_ff <= 8:
                    from matplotlib.patches import Patch
                    ax.legend(handles=[Patch(facecolor="C%d" % i, label=st) for i, st in enumerate(strata_plot_ff)], loc="best", fontsize=8)
                plt.tight_layout()
                _plot_save(res_dir / "ml_formula_feat_error_boxplot.png")
    else:
        print("\nFormula columns (SRKT/Holladay1/Haigis _SE_pred_actualIOL) not all present. Skip formula-as-feature analysis.\n")

    # --- Multimodal: subset where B超, A, T, N are all non-empty; add them as features ---
    baseline_test_mae = {name: result_df[(result_df["Split"] == "Test") & (result_df["Stratum"] == "Overall") & (result_df["Model"] == name)]["MAE"].values[0] for name in models}
    baseline_test_r2 = {name: result_df[(result_df["Split"] == "Test") & (result_df["Stratum"] == "Overall") & (result_df["Model"] == name)]["R2"].values[0] for name in models}

    if all(c in df.columns for c in MULTIMODAL_COLS):
        mask_mm = valid.copy()
        for c in MULTIMODAL_COLS:
            if df[c].dtype == object or df[c].dtype.name == "string":
                mask_mm &= df[c].notna() & (df[c].astype(str).str.strip() != "")
            else:
                mask_mm &= df[c].notna()
        df_mm = df.loc[mask_mm].copy()
        df_mm["ATN_score"] = _build_atn_score(df_mm)
        y_mm = _to_numeric(df_mm[TARGET_NAME])
        df_mm = df_mm[~y_mm.isna() & df_mm["ATN_score"].notna()]
        y_mm = y_mm.loc[df_mm.index]
        if len(df_mm) < 50:
            print("\nMultimodal: too few rows with B超 + ATN score and 术后SE (n=%d). Skip.\n" % len(df_mm))
        else:
            feat_cols_mm = [c for c in FEAT_NAMES if c in df_mm.columns]
            df_mm["B超_enc"] = pd.factorize(df_mm["B超"].astype(str).str.strip())[0]
            feat_cols_mm = feat_cols_mm + ["B超_enc", "ATN_score"]
            X_mm = df_mm[feat_cols_mm].copy()
            stratum_mm = stratum.loc[df_mm.index].copy()

            try:
                i_tr, i_te = train_test_split(np.arange(len(y_mm)), test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=stratum_mm.values)
            except Exception:
                i_tr, i_te = train_test_split(np.arange(len(y_mm)), test_size=TEST_SIZE, random_state=RANDOM_STATE)
            train_idx_mm = df_mm.index[i_tr]
            test_idx_mm = df_mm.index[i_te]
            X_train_mm = X_mm.loc[train_idx_mm]
            X_test_mm = X_mm.loc[test_idx_mm]
            y_train_mm = y_mm.loc[train_idx_mm]
            y_test_mm = y_mm.loc[test_idx_mm]
            stratum_test_mm = stratum_mm.loc[test_idx_mm].values

            imp_mm = SimpleImputer(strategy="median")
            X_train_mm_imp = pd.DataFrame(imp_mm.fit_transform(X_train_mm), columns=feat_cols_mm, index=train_idx_mm)
            X_test_mm_imp = pd.DataFrame(imp_mm.transform(X_test_mm), columns=feat_cols_mm, index=test_idx_mm)
            scaler_mm = StandardScaler()
            X_train_mm_s = scaler_mm.fit_transform(X_train_mm_imp)
            X_test_mm_s = scaler_mm.transform(X_test_mm_imp)

            models_mm = {
                "LinearRegression": LinearRegression(),
                "SVR": SVR(kernel="rbf", C=10.0, epsilon=0.1),
                "RandomForest": RandomForestRegressor(n_estimators=100, max_depth=10, random_state=RANDOM_STATE),
                "MLP": MLPRegressor(hidden_layer_sizes=(64, 32), max_iter=500, random_state=RANDOM_STATE),
            }
            if HAS_XGB:
                models_mm["XGBoost"] = xgb.XGBRegressor(n_estimators=100, max_depth=6, random_state=RANDOM_STATE)

            rows_mm = []
            pred_test_mm = {}
            fitted_mm = {}
            print("\n--- Multimodal (B超 + ATN_score): n = %d (train %d, test %d) ---\n" % (len(df_mm), len(y_train_mm), len(y_test_mm)))
            print("Features:", feat_cols_mm)
            for name, est in models_mm.items():
                X_tr = X_train_mm_s if name in use_scaled else X_train_mm_imp.values
                X_te = X_test_mm_s if name in use_scaled else X_test_mm_imp.values
                est.fit(X_tr, y_train_mm)
                fitted_mm[name] = est
                pred_train_mm = est.predict(X_tr)
                pred_te = est.predict(X_te)
                pred_test_mm[name] = pred_te
                mt = compute_metrics(y_train_mm, pred_train_mm)
                me = compute_metrics(y_test_mm, pred_te)
                rows_mm.append({"Model": name, "Split": "Train", "Stratum": "Overall", "n": mt["n"], "MAE": mt["MAE"], "RMSE": mt["RMSE"], "MedAE": mt["MedAE"], "R2": mt["R2"], "pct_within_0.25": mt["pct_0.25"], "pct_within_0.5": mt["pct_0.5"], "pct_within_1": mt["pct_1"]})
                rows_mm.append({"Model": name, "Split": "Test", "Stratum": "Overall", "n": me["n"], "MAE": me["MAE"], "RMSE": me["RMSE"], "MedAE": me["MedAE"], "R2": me["R2"], "pct_within_0.25": me["pct_0.25"], "pct_within_0.5": me["pct_0.5"], "pct_within_1": me["pct_1"]})
                for st in np.unique(stratum_test_mm):
                    msk = stratum_test_mm == st
                    if np.sum(msk) < 2:
                        continue
                    me_st = compute_metrics(y_test_mm.values[msk], pred_te[msk])
                    rows_mm.append({"Model": name, "Split": "Test", "Stratum": st, "n": me_st["n"], "MAE": me_st["MAE"], "RMSE": me_st["RMSE"], "MedAE": me_st["MedAE"], "R2": me_st["R2"], "pct_within_0.25": me_st["pct_0.25"], "pct_within_0.5": me_st["pct_0.5"], "pct_within_1": me_st["pct_1"]})
                print(name, " Test MAE =", round(me["MAE"], 4), " R2 =", round(me["R2"], 4), " | +/-0.5 D:", round(me["pct_0.5"], 1), "%")

            result_mm = pd.DataFrame(rows_mm)
            out_mm = res_dir / "ml_postSE_comparison_multimodal.csv"
            result_mm.to_csv(out_mm, index=False, encoding="gb2312")
            print("Saved:", out_mm)
            run_paired_inference_mae(
                y_true=y_test_mm.values,
                pred_test_by_model=pred_test_mm,
                model_order=list(models_mm.keys()),
                res_dir=res_dir,
                prefix="ml_postSE_multimodal",
            )

            # SHAP feature ranking + summary & beeswarm plots (multimodal models)
            if HAS_SHAP and not args.no_shap and fitted_mm:
                print("\n--- SHAP feature ranking and plots (multimodal) ---")
                shap_mm_rows = []
                for name in fitted_mm:
                    X_tr = X_train_mm_s if name in use_scaled else X_train_mm_imp.values
                    df_rank = compute_shap_ranking_and_plots(
                        fitted_mm[name], X_tr, feat_cols_mm, name, res_dir, prefix="multimodal_"
                    )
                    if df_rank is not None:
                        shap_mm_rows.append(df_rank)
                        print("  %s: top 3 features" % name, list(df_rank.head(3)["Feature"].values))
                if shap_mm_rows:
                    shap_mm_df = pd.concat(shap_mm_rows, ignore_index=True)
                    out_shap_mm = res_dir / "shap_ranking_multimodal.csv"
                    shap_mm_df.to_csv(out_shap_mm, index=False, encoding="utf-8")
                    print("Saved:", out_shap_mm)

            test_records_mm = []
            for i, idx in enumerate(test_idx_mm):
                rec = {"术后SE": y_test_mm.loc[idx], "Stratum": stratum_test_mm[i]}
                for name, pred in pred_test_mm.items():
                    rec["Model"] = name
                    rec["Predicted"] = pred[i]
                    test_records_mm.append(rec.copy())
            test_long_mm = pd.DataFrame(test_records_mm)
            test_long_mm["Mean"] = (test_long_mm["术后SE"] + test_long_mm["Predicted"]) / 2
            test_long_mm["Diff"] = test_long_mm["Predicted"] - test_long_mm["术后SE"]
            test_metrics_mm = result_mm[result_mm["Split"] == "Test"].copy()
            test_long_mm_plot = test_long_mm[test_long_mm["Stratum"] != "Overall"]

            if not args.no_plots:
                n_models = len(models_mm)
                ncol = min(3, n_models)
                nrow = (n_models + ncol - 1) // ncol
                fig, axes = plt.subplots(nrow, ncol, figsize=(4 * ncol, 4 * nrow))
                axes = np.atleast_1d(axes).flatten()
                for k, (name, ax) in enumerate(zip(models_mm.keys(), axes)):
                    sub = test_long_mm_plot[test_long_mm_plot["Model"] == name]
                    for st in sub["Stratum"].unique():
                        s = sub[sub["Stratum"] == st]
                        ax.scatter(s["术后SE"], s["Predicted"], label=st, alpha=0.65, s=20)
                    ax.plot([sub["术后SE"].min(), sub["术后SE"].max()], [sub["术后SE"].min(), sub["术后SE"].max()], "k--", lw=1)
                    ax.set_xlabel("Actual 术后SE (D)")
                    ax.set_ylabel("Predicted (D)")
                    ax.set_title(name)
                    ax.legend(loc="best", fontsize=8)
                    ax.grid(True, alpha=0.3)
                for k in range(n_models, len(axes)):
                    axes[k].set_visible(False)
                fig.suptitle("ML Multimodal: Predicted vs Actual (test)")
                plt.tight_layout()
                _plot_save(res_dir / "ml_multimodal_actual_vs_predicted_scatter.png")

                plot_mm = test_metrics_mm[(test_metrics_mm["n"] >= 2) & (test_metrics_mm["Stratum"] != "Overall")]
                strata_mm_uniq = sorted(plot_mm["Stratum"].unique()) if len(plot_mm) > 0 else []
                if len(plot_mm) > 0 and len(strata_mm_uniq) > 0:
                    model_names_mm = list(models_mm.keys())
                    x = np.arange(len(model_names_mm))
                    width = 0.8 / max(len(strata_mm_uniq), 1)
                    fig, ax = plt.subplots(figsize=(10, 5))
                    for i, st in enumerate(strata_mm_uniq):
                        sub = plot_mm[plot_mm["Stratum"] == st]
                        mae_vals = [sub[sub["Model"] == m]["MAE"].values[0] if len(sub[sub["Model"] == m]) else np.nan for m in model_names_mm]
                        off = (i - len(strata_mm_uniq) / 2) * width + width / 2
                        ax.bar(x + off, mae_vals, width, label=st)
                    ax.set_xticks(x)
                    ax.set_xticklabels(model_names_mm, rotation=25, ha="right")
                    ax.set_ylabel("MAE (D)")
                    ax.set_title("Multimodal: Test MAE by Model and Cataract Type")
                    ax.legend(loc="best", fontsize=8)
                    ax.grid(True, axis="y", alpha=0.3)
                    plt.tight_layout()
                    _plot_save(res_dir / "ml_multimodal_MAE_by_stratum.png")

                    fig, ax = plt.subplots(figsize=(10, 5))
                    for i, st in enumerate(strata_mm_uniq):
                        sub = plot_mm[plot_mm["Stratum"] == st]
                        pct_vals = [sub[sub["Model"] == m]["pct_within_0.5"].values[0] if len(sub[sub["Model"] == m]) else np.nan for m in model_names_mm]
                        off = (i - len(strata_mm_uniq) / 2) * width + width / 2
                        ax.bar(x + off, pct_vals, width, label=st)
                    ax.set_xticks(x)
                    ax.set_xticklabels(model_names_mm, rotation=25, ha="right")
                    ax.set_ylabel("% within +/-0.5 D")
                    ax.set_title("Multimodal: % within +/-0.5 D by Model and Cataract Type")
                    ax.axhline(50, color="gray", linestyle=":", lw=1)
                    ax.axhline(75, color="gray", linestyle=":", lw=1)
                    ax.axhline(90, color="gray", linestyle=":", lw=1)
                    ax.set_ylim(0, 100)
                    ax.legend(loc="best", fontsize=8)
                    ax.grid(True, axis="y", alpha=0.3)
                    plt.tight_layout()
                    _plot_save(res_dir / "ml_multimodal_pct_within_0.5_by_stratum.png")

                fig, axes = plt.subplots(nrow, ncol, figsize=(4 * ncol, 4 * nrow))
                axes = np.atleast_1d(axes).flatten()
                for k, name in enumerate(models_mm.keys()):
                    sub = test_long_mm_plot[test_long_mm_plot["Model"] == name]
                    for st in sub["Stratum"].unique():
                        s = sub[sub["Stratum"] == st]
                        axes[k].scatter(s["Mean"], s["Diff"], label=st, alpha=0.6, s=18)
                    m, sd = sub["Diff"].mean(), sub["Diff"].std()
                    axes[k].axhline(m, color="darkred", linestyle="-", lw=1)
                    axes[k].axhline(m - 1.96 * sd, color="gray", linestyle="--", lw=0.8)
                    axes[k].axhline(m + 1.96 * sd, color="gray", linestyle="--", lw=0.8)
                    axes[k].set_xlabel("Mean (Actual, Predicted) (D)")
                    axes[k].set_ylabel("Predicted - Actual (D)")
                    axes[k].set_title(name)
                    axes[k].legend(loc="best", fontsize=8)
                    axes[k].grid(True, alpha=0.3)
                for k in range(n_models, len(axes)):
                    axes[k].set_visible(False)
                fig.suptitle("ML Multimodal: Bland-Altman (test)")
                plt.tight_layout()
                _plot_save(res_dir / "ml_multimodal_bland_altman.png")

                strata_plot_mm = sorted([s for s in test_long_mm["Stratum"].unique() if s != "Overall"])
                n_strata_mm = len(strata_plot_mm)
                w = 0.8 / max(n_strata_mm, 1)
                positions_mm, data_list_mm = [], []
                for j, name in enumerate(models_mm.keys()):
                    sub = test_long_mm_plot[test_long_mm_plot["Model"] == name]
                    for i, st in enumerate(strata_plot_mm):
                        s = sub[sub["Stratum"] == st]["Diff"]
                        positions_mm.append(j + (i - n_strata_mm / 2) * w + w / 2)
                        data_list_mm.append(s if len(s) > 0 else [np.nan])
                fig, ax = plt.subplots(figsize=(10, 5))
                ax.boxplot(data_list_mm, positions=positions_mm, widths=w * 0.8, patch_artist=True, showfliers=True)
                ax.axhline(0, color="gray", linestyle="--", lw=1)
                ax.set_xticks(range(len(models_mm)))
                ax.set_xticklabels(list(models_mm.keys()), rotation=25, ha="right")
                ax.set_ylabel("Prediction error (D)")
                ax.set_title("Multimodal: Prediction Error by Model and Cataract Type")
                ax.grid(True, axis="y", alpha=0.3)
                if n_strata_mm <= 8:
                    from matplotlib.patches import Patch
                    ax.legend(handles=[Patch(facecolor="C%d" % i, label=st) for i, st in enumerate(strata_plot_mm)], loc="best", fontsize=8)
                plt.tight_layout()
                _plot_save(res_dir / "ml_multimodal_error_boxplot.png")

            print("\n--- Comparison: Baseline vs Formula-feat vs Multimodal (Test MAE / R2) ---")
            for name in models_mm:
                b_mae = baseline_test_mae.get(name, np.nan)
                b_r2 = baseline_test_r2.get(name, np.nan)
                m_mae = result_mm[(result_mm["Split"] == "Test") & (result_mm["Stratum"] == "Overall") & (result_mm["Model"] == name)]["MAE"].values[0]
                m_r2 = result_mm[(result_mm["Split"] == "Test") & (result_mm["Stratum"] == "Overall") & (result_mm["Model"] == name)]["R2"].values[0]
                f_mae = np.nan
                f_r2 = np.nan
                if result_ff is not None and name in result_ff["Model"].values:
                    r = result_ff[(result_ff["Split"] == "Test") & (result_ff["Stratum"] == "Overall") & (result_ff["Model"] == name)]
                    if len(r) > 0:
                        f_mae, f_r2 = r["MAE"].values[0], r["R2"].values[0]
                print("  %s: Baseline MAE=%.4f R2=%.4f  |  Formula-feat MAE=%.4f R2=%.4f  |  Multimodal MAE=%.4f R2=%.4f" % (name, b_mae, b_r2, f_mae, f_r2, m_mae, m_r2))
    else:
        print("\nColumns B超, A, T, N not all present. Skip multimodal analysis.\n")


if __name__ == "__main__":
    main()
