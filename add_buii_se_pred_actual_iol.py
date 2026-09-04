# -*- coding: utf-8 -*-
"""
Add column BUII_SE_pred_actualIOL to 杨宁整合四文件合并_计算结果.xlsx:
- Use actual IOL (column IOL) and IOL_Power_Table (JSON: [{"IOL_Power": x, "Refraction": y}, ...]).
- Find the IOL_Power closest to actual IOL and set BUII_SE_pred_actualIOL = that Refraction.

Run from project root:
  python add_buii_se_pred_actual_iol.py
  python add_buii_se_pred_actual_iol.py -i data/杨宁整合四文件合并_计算结果.xlsx -o data/杨宁整合四文件合并_计算结果.xlsx
"""

import argparse
import json
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE / "data" / "杨宁整合四文件合并_计算结果.xlsx"


def parse_iol_power_table(s):
    """
    Parse JSON string like [{"IOL_Power": 8.5, "Refraction": -4.01}, ...] into list of (power, refraction).
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
    out = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        power = item.get("IOL_Power")
        refr = item.get("Refraction")
        if power is None or refr is None:
            continue
        try:
            out.append((float(power), float(refr)))
        except (TypeError, ValueError):
            continue
    return out


def find_closest_se(iol_table_list, actual_iol):
    """
    Find IOL power in table closest to actual_iol, return corresponding Refraction.
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


def find_iol_col(df):
    for c in df.columns:
        if str(c).strip() == "IOL":
            return c
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Add BUII_SE_pred_actualIOL from IOL_Power_Table (closest IOL power -> Refraction)."
    )
    parser.add_argument("-i", "--input", type=str, default=None,
                        help="Input Excel (default: data/杨宁整合四文件合并_计算结果.xlsx)")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="Output Excel (default: overwrite input)")
    args = parser.parse_args()

    in_path = Path(args.input) if args.input else DEFAULT_INPUT
    if not in_path.is_absolute():
        in_path = BASE / in_path
    out_path = Path(args.output) if args.output else in_path
    if not out_path.is_absolute():
        out_path = BASE / out_path

    if not in_path.exists():
        print(f"Input file not found: {in_path}")
        return

    df = pd.read_excel(in_path, sheet_name=0)

    if find_iol_col(df) is None:
        print("Input has no IOL column. Abort.")
        return
    if "IOL_Power_Table" not in df.columns:
        print("Input has no IOL_Power_Table column. Abort.")
        return

    iol_col = find_iol_col(df)
    se_pred_list = []
    for i in range(len(df)):
        actual_iol = df[iol_col].iloc[i]
        table_str = df["IOL_Power_Table"].iloc[i]
        table_list = parse_iol_power_table(table_str)
        se_pred = find_closest_se(table_list, actual_iol)
        se_pred_list.append(se_pred)

    df["BUII_SE_pred_actualIOL"] = se_pred_list
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out_path, index=False)
    n_filled = sum(1 for x in se_pred_list if x is not None)
    print(f"Added BUII_SE_pred_actualIOL: {n_filled}/{len(se_pred_list)} filled. Saved: {out_path}")


if __name__ == "__main__":
    main()
