import pandas as pd
import numpy as np
from pathlib import Path

from ml_postSE_models import (
    compute_shap_ranking_and_plots,
    _build_atn_score,
    _to_numeric,
    RANDOM_STATE,
    HAS_SHAP,
)


def main() -> None:
    base = Path(".").resolve()
    res_dir = base / "results"
    data_dir = base / "data"
    # Use glob to avoid encoding issues in Chinese filename
    candidates = sorted(data_dir.glob("*merged_SE_pred_with_hillrbf.xlsx"))
    if not candidates:
        candidates = sorted(data_dir.glob("*merged_SE_pred.xlsx"))
    if not candidates:
        raise FileNotFoundError("No merged_SE_pred Excel file found in data directory.")
    in_path = candidates[0]

    df = pd.read_excel(in_path)
    if "术后SE" not in df.columns:
        raise ValueError("术后SE column not found in input.")

    valid = ~pd.to_numeric(df["术后SE"], errors="coerce").isna()
    mm_cols = ["B超", "A", "T", "N"]
    mask = valid.copy()
    for c in mm_cols:
        if c in df.columns:
            ser = df[c]
            if ser.dtype == object or ser.dtype.name == "string":
                mask &= ser.notna() & (ser.astype(str).str.strip() != "")
            else:
                mask &= ser.notna()
    mm = df.loc[mask].copy()

    mm["ATN_score"] = _build_atn_score(mm)
    y = _to_numeric(mm["术后SE"])
    mm = mm.loc[~y.isna() & mm["ATN_score"].notna()]
    y = y.loc[mm.index]

    mm["B超_enc"] = pd.factorize(mm["B超"].astype(str).str.strip())[0]

    feat_cols_mm = [
        "AL",
        "ACD",
        "LT",
        "CCT",
        "W2W",
        "K1",
        "K2",
        "预留",
        "IOL",
        "B超_enc",
        "ATN_score",
    ]
    missing = [c for c in feat_cols_mm if c not in mm.columns]
    if missing:
        raise ValueError(f"Missing multimodal feature columns: {missing}")

    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LinearRegression
    from sklearn.svm import SVR
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.neural_network import MLPRegressor
    try:
        import xgboost as xgb
        has_xgb = True
    except Exception:
        has_xgb = False

    imp = SimpleImputer(strategy="median")
    X_imp = pd.DataFrame(
        imp.fit_transform(mm[feat_cols_mm]),
        columns=feat_cols_mm,
        index=mm.index,
    )
    scaler = StandardScaler()
    X_s = scaler.fit_transform(X_imp)

    if not HAS_SHAP:
        print("SHAP not installed; cannot compute multimodal SHAP rankings.")
        return

    models = {
        "LinearRegression": LinearRegression(),
        "SVR": SVR(kernel="rbf", C=10.0, epsilon=0.1),
        "RandomForest": RandomForestRegressor(
            n_estimators=100,
            max_depth=10,
            random_state=RANDOM_STATE,
        ),
        "MLP": MLPRegressor(
            hidden_layer_sizes=(64, 32),
            max_iter=500,
            random_state=RANDOM_STATE,
        ),
    }
    if has_xgb:
        models["XGBoost"] = xgb.XGBRegressor(
            n_estimators=100,
            max_depth=6,
            random_state=RANDOM_STATE,
        )

    rows = []
    for name, est in models.items():
        if name in ["LinearRegression", "SVR", "MLP"]:
            X_tr = X_s
        else:
            X_tr = X_imp.values
        est.fit(X_tr, y)
        df_rank = compute_shap_ranking_and_plots(
            est,
            X_tr,
            feat_cols_mm,
            name,
            res_dir,
            prefix="multimodal_",
            max_background=200,
            nsamples_kernel=50,
        )
        if df_rank is not None:
            rows.append(df_rank)

    if rows:
        out = pd.concat(rows, ignore_index=True)
        out_path = res_dir / "shap_ranking_multimodal.csv"
        out.to_csv(out_path, index=False, encoding="utf-8")
        print("Saved:", out_path)
    else:
        print("No SHAP rankings computed for multimodal models.")


if __name__ == "__main__":
    main()

