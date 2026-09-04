# -*- coding: utf-8 -*-
"""
Add column EVO_SE_pred_actualIOL to EVO results Excel:
- For each row: use actual IOL (column IOL).
- Among EVO_iol_1..EVO_iol_5, find the one closest to actual IOL.
- Set EVO_SE_pred_actualIOL = the corresponding EVO_ref (EVO_ref_1..EVO_ref_5).

Run from project root:
  python add_evo_se_pred_actual_iol.py
  python add_evo_se_pred_actual_iol.py -i data/xxx.xlsx -o data/xxx_out.xlsx
"""

import argparse
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE / "data" / "杨宁整合四文件合并_填补后_evo_results.xlsx"

IOL_COLS = ["EVO_iol_1", "EVO_iol_2", "EVO_iol_3", "EVO_iol_4", "EVO_iol_5"]
REF_COLS = ["EVO_ref_1", "EVO_ref_2", "EVO_ref_3", "EVO_ref_4", "EVO_ref_5"]


def to_float(x):
    if pd.isna(x):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return None


def find_closest_ref(df_row, actual_iol, iol_cols, ref_cols):
    """
    From one row: get (EVO_iol_k, EVO_ref_k) for k=1..5 where both are valid.
    Find k with EVO_iol_k closest to actual_iol; return EVO_ref_k.
    Returns None if actual_iol invalid or no valid pairs.
    """
    actual = to_float(actual_iol)
    if actual is None:
        return None
    best_ref = None
    best_diff = float("inf")
    for iol_col, ref_col in zip(iol_cols, ref_cols):
        if iol_col not in df_row.index or ref_col not in df_row.index:
            continue
        iol_val = to_float(df_row[iol_col])
        ref_val = to_float(df_row[ref_col])
        if iol_val is None or ref_val is None:
            continue
        diff = abs(iol_val - actual)
        if diff < best_diff:
            best_diff = diff
            best_ref = ref_val
    return best_ref


def find_iol_col(df):
    for c in df.columns:
        if str(c).strip() == "IOL":
            return c
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Add EVO_SE_pred_actualIOL: predicted SE for actual IOL from EVO_iol/EVO_ref columns."
    )
    parser.add_argument("-i", "--input", type=str, default=None,
                        help="Input Excel (default: data/杨宁整合四文件合并_填补后_evo_results.xlsx)")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="Output Excel (default: overwrite input with same name)")
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
    iol_col = find_iol_col(df)
    if iol_col is None:
        print("Input has no IOL column. Abort.")
        return
    missing = [c for c in IOL_COLS + REF_COLS if c not in df.columns]
    if missing:
        print(f"Input missing columns: {missing}. Abort.")
        return

    se_list = []
    for i in range(len(df)):
        actual_iol = df[iol_col].iloc[i]
        ref_val = find_closest_ref(df.iloc[i], actual_iol, IOL_COLS, REF_COLS)
        se_list.append(ref_val)

    df["EVO_SE_pred_actualIOL"] = se_list
    n_filled = sum(1 for x in se_list if x is not None)
    print(f"Added EVO_SE_pred_actualIOL: {n_filled}/{len(se_list)} filled.")

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
