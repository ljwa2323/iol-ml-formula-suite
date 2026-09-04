# -*- coding: utf-8 -*-
"""
Add 3 columns to 杨宁整合四文件合并_七档目标屈光IOL_网页.json列.xlsx:
  Shammas_SE_pred_actualIOL, Haigis_L_SE_pred_actualIOL, Barrett_True_K_SE_pred_actualIOL.

For each row: use actual IOL and the 7-target JSON (IOL_calc_7targets_web_json).
For each formula, interpolate target_ref_D (SE) that corresponds to the actual IOL.
So we get the predicted SE that each formula would have planned for this actual IOL.

Run from project root:
  python add_7targets_se_pred_actual_iol.py
  python add_7targets_se_pred_actual_iol.py -i data/xxx.xlsx -o data/xxx_out.xlsx
"""

import argparse
import json
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE / "data" / "杨宁整合四文件合并_七档目标屈光IOL_网页.json列.xlsx"

FORMULA_IOL_KEYS = (
    ("Shammas", "Shammas_IOL_D"),
    ("Haigis_L", "Haigis_L_IOL_D"),
    ("Barrett_True_K", "Barrett_True_K_IOL_D"),
)


def parse_7targets_json(s):
    """
    Parse IOL_calc_7targets_web_json string into list of dicts.
    Each dict has target_ref_D, Shammas_IOL_D, Haigis_L_IOL_D, Barrett_True_K_IOL_D.
    Returns [] if invalid or empty.
    """
    if pd.isna(s) or not isinstance(s, str) or not s.strip():
        return []
    try:
        arr = json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(arr, list):
        return []
    return arr


def _to_float(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return None


def interpolate_se_for_actual_iol(points_iol_se, actual_iol):
    """
    points_iol_se: list of (iol_power, target_ref_D) sorted by iol_power.
    Find target_ref_D (SE) corresponding to actual_iol by linear interpolation.
    Returns None if points empty or actual_iol invalid; else interpolated or extrapolated SE.
    """
    if not points_iol_se or pd.isna(actual_iol):
        return None
    try:
        actual = float(actual_iol)
    except (TypeError, ValueError):
        return None
    points = sorted([(float(i), float(s)) for i, s in points_iol_se if i is not None and s is not None])
    if not points:
        return None
    iols = [p[0] for p in points]
    ses = [p[1] for p in points]
    if actual <= iols[0]:
        return ses[0] if actual == iols[0] else _extrapolate(iols[0], ses[0], iols[1], ses[1], actual)
    if actual >= iols[-1]:
        return ses[-1] if actual == iols[-1] else _extrapolate(iols[-2], ses[-2], iols[-1], ses[-1], actual)
    for k in range(len(iols) - 1):
        if iols[k] <= actual <= iols[k + 1]:
            t = (actual - iols[k]) / (iols[k + 1] - iols[k]) if iols[k + 1] != iols[k] else 0
            return ses[k] + t * (ses[k + 1] - ses[k])
    return ses[-1]


def _extrapolate(x0, y0, x1, y1, x):
    if x1 == x0:
        return y0
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def build_points_for_formula(rows, iol_key, target_key="target_ref_D"):
    """From list of row dicts, build [(iol_d, target_ref_D), ...] for one formula."""
    points = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        se = r.get(target_key) or r.get("目标屈光度")
        iol = r.get(iol_key)
        se_f = _to_float(se)
        iol_f = _to_float(iol)
        if iol_f is not None and se_f is not None:
            points.append((iol_f, se_f))
    return points


def find_iol_col(df):
    for c in df.columns:
        if str(c).strip() == "IOL":
            return c
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Add Shammas/Haigis_L/Barrett_True_K SE_pred_actualIOL from 7-target web JSON."
    )
    parser.add_argument("-i", "--input", type=str, default=None,
                        help="Input Excel (default: data/杨宁整合四文件合并_七档目标屈光IOL_网页.json列.xlsx)")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="Output Excel (default: input dir, stem_with_7targets_SE.xlsx)")
    args = parser.parse_args()

    in_path = Path(args.input) if args.input else DEFAULT_INPUT
    if not in_path.is_absolute():
        in_path = BASE / in_path
    if args.output:
        out_path = Path(args.output)
    else:
        # Default: write to new file to avoid PermissionError when input is open in Excel
        out_path = in_path.parent / (in_path.stem + "_with_7targets_SE" + in_path.suffix)
    if not out_path.is_absolute():
        out_path = BASE / out_path

    if not in_path.exists():
        print(f"Input file not found: {in_path}")
        return

    df = pd.read_excel(in_path, sheet_name=0)
    if find_iol_col(df) is None:
        print("Input has no IOL column. Abort.")
        return
    json_col = "IOL_calc_7targets_web_json"
    if json_col not in df.columns:
        print(f"Input has no {json_col} column. Abort.")
        return

    iol_col = find_iol_col(df)
    for formula_name, iol_key in FORMULA_IOL_KEYS:
        col_name = f"{formula_name}_SE_pred_actualIOL"
        se_list = []
        for i in range(len(df)):
            actual_iol = df[iol_col].iloc[i]
            raw = df[json_col].iloc[i]
            rows = parse_7targets_json(raw)
            points = build_points_for_formula(rows, iol_key)
            se = interpolate_se_for_actual_iol(points, actual_iol)
            se_list.append(se)
        df[col_name] = se_list
        n_filled = sum(1 for x in se_list if x is not None)
        print(f"Added {col_name}: {n_filled}/{len(se_list)} filled.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_excel(out_path, index=False)
        print(f"Saved: {out_path}")
    except PermissionError:
        alt = out_path.parent / (out_path.stem + "_alt" + out_path.suffix)
        df.to_excel(alt, index=False)
        print(f"Permission denied writing to {out_path}. Saved to: {alt}")


if __name__ == "__main__":
    main()
