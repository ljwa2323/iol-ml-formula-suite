# -*- coding: utf-8 -*-
"""
Add column Kane_SE_pred_actualIOL to Kane results:
- Join with fill file (杨宁整合四文件合并_填补后.xlsx) on (ID, Eye) to get actual IOL used.
- Parse Kane_IOL_Table (e.g. "8.0:-4.68; 7.5:-4.34; ...") and find the IOL power closest to actual IOL.
- Set Kane_SE_pred_actualIOL = the predicted SE (refraction) for that closest IOL.

Run from project root:
  python add_kane_se_pred_actual_iol.py
  python add_kane_se_pred_actual_iol.py --kane data/Kane_results_merged.xlsx --fill data/杨宁整合四文件合并_填补后.xlsx -o data/Kane_results_with_SE_pred.xlsx
"""

import argparse
import re
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
DEFAULT_FILL = BASE / "data" / "杨宁整合四文件合并_填补后.xlsx"
DEFAULT_KANE = BASE / "data" / "Kane_results_merged.xlsx"


def norm_eye(v):
    if pd.isna(v) or str(v).strip() == "":
        return "OD"
    s = str(v).strip().upper()
    if s in ("OD", "OS", "R", "L"):
        return "OD" if s in ("OD", "R") else "OS"
    return s


def parse_kane_iol_table(s):
    """
    Parse "8.0:-4.68; 7.5:-4.34; 7.0:-4.01; ..." into list of (power, se_pred).
    Returns [] if invalid or empty.
    """
    if pd.isna(s) or not isinstance(s, str) or not s.strip():
        return []
    out = []
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"([-\d.]+)\s*:\s*([-\d.]+)", part)
        if m:
            try:
                power = float(m.group(1))
                se_pred = float(m.group(2))
                out.append((power, se_pred))
            except ValueError:
                continue
    return out


def find_closest_se(iol_table_list, actual_iol):
    """
    Find IOL power in table closest to actual_iol, return corresponding SE prediction.
    Returns None if table empty or actual_iol is NaN/invalid.
    """
    if not iol_table_list or pd.isna(actual_iol):
        return None
    try:
        actual = float(actual_iol)
    except (TypeError, ValueError):
        return None
    best_se = None
    best_diff = float("inf")
    for power, se_pred in iol_table_list:
        diff = abs(power - actual)
        if diff < best_diff:
            best_diff = diff
            best_se = se_pred
    return best_se


def find_id_col(df):
    for c in df.columns:
        if str(c).strip() == "ID" or str(c).strip().lower() == "id":
            return c
    return df.columns[0]


def find_eye_col(df):
    for c in df.columns:
        if "眼别" in str(c) or str(c).strip() in ("Eye", "eye"):
            return c
    return None


def find_iol_col(df):
    for c in df.columns:
        if str(c).strip() == "IOL":
            return c
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Add Kane_SE_pred_actualIOL: predicted SE for actual IOL from Kane_IOL_Table."
    )
    parser.add_argument("--kane", type=str, default=None, help="Kane results Excel (default: data/Kane_results_merged.xlsx)")
    parser.add_argument("--fill", type=str, default=None, help="Fill file Excel with IOL column (default: data/杨宁整合四文件合并_填补后.xlsx)")
    parser.add_argument("-o", "--output", type=str, default=None, help="Output Excel (default: overwrite --kane)")
    args = parser.parse_args()

    kane_path = Path(args.kane) if args.kane else DEFAULT_KANE
    fill_path = Path(args.fill) if args.fill else DEFAULT_FILL
    out_path = Path(args.output) if args.output else kane_path
    if not out_path.is_absolute():
        out_path = BASE / out_path

    if not kane_path.exists():
        print(f"Kane file not found: {kane_path}")
        return
    if not fill_path.exists():
        print(f"Fill file not found: {fill_path}")
        return

    df_kane = pd.read_excel(kane_path, sheet_name=0)
    df_fill = pd.read_excel(fill_path, sheet_name=0)

    kane_id = find_id_col(df_kane)
    kane_eye = "Eye" if "Eye" in df_kane.columns else find_eye_col(df_kane)
    if kane_eye is None:
        kane_eye = [c for c in df_kane.columns if "eye" in c.lower() or "眼" in c]
        kane_eye = kane_eye[0] if kane_eye else df_kane.columns[2]

    fill_id = find_id_col(df_fill)
    fill_eye = find_eye_col(df_fill)
    fill_iol = find_iol_col(df_fill)
    if fill_iol is None:
        print("Fill file has no IOL column. Abort.")
        return

    # Build (id, eye) -> actual IOL from fill (normalize id strip, eye OD/OS)
    fill_id_norm = df_fill[fill_id].astype(str).str.strip()
    fill_eye_norm = df_fill[fill_eye].apply(norm_eye)
    actual_iol_map = {}
    for i, (id_, eye) in enumerate(zip(fill_id_norm, fill_eye_norm)):
        key = (id_, eye)
        val = df_fill[fill_iol].iloc[i]
        if key in actual_iol_map:
            continue
        actual_iol_map[key] = val

    if "Kane_IOL_Table" not in df_kane.columns:
        print("Kane file has no Kane_IOL_Table column. Abort.")
        return

    # For each Kane row: (id, eye) -> actual IOL, parse table, closest SE
    kane_id_norm = df_kane[kane_id].astype(str).str.strip()
    kane_eye_norm = df_kane[kane_eye].apply(norm_eye)
    se_pred_list = []
    for i in range(len(df_kane)):
        key = (kane_id_norm.iloc[i], kane_eye_norm.iloc[i])
        actual_iol = actual_iol_map.get(key)
        table_str = df_kane["Kane_IOL_Table"].iloc[i]
        table_list = parse_kane_iol_table(table_str)
        se_pred = find_closest_se(table_list, actual_iol)
        se_pred_list.append(se_pred)

    df_kane["Kane_SE_pred_actualIOL"] = se_pred_list
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_kane.to_excel(out_path, index=False)
    n_filled = sum(1 for x in se_pred_list if x is not None)
    print(f"Added Kane_SE_pred_actualIOL: {n_filled}/{len(se_pred_list)} filled. Saved: {out_path}")


if __name__ == "__main__":
    main()
