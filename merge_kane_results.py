# -*- coding: utf-8 -*-
"""
Merge multiple Kane result Excel files into one.
- Uses (ID, Eye) as key; later file overwrites earlier for duplicates.
- Default: merge Kane_results.xlsx + two kane_missing_*.xlsx into one output.

Run from project root:
  python merge_kane_results.py
  python merge_kane_results.py --output data/Kane_results_merged.xlsx
"""

import argparse
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
DEFAULT_FILES = [
    BASE / "batch_calculators" / "Kane_results.xlsx",
    BASE / "data" / "kane_missing_20260208_205817.xlsx",
    BASE / "data" / "kane_missing_20260209_094525.xlsx",
]


def find_id_col(df):
    for c in df.columns:
        s = str(c).strip()
        if s == "ID" or s.lower() == "id":
            return c
    return df.columns[0]


def find_eye_col(df):
    for c in df.columns:
        if "Eye" in str(c) or "eye" in str(c).lower() or "眼别" in str(c):
            return c
    return None


def norm_eye(v):
    if pd.isna(v) or str(v).strip() == "":
        return "OD"
    s = str(v).strip().upper()
    if s in ("OD", "OS", "R", "L"):
        return "OD" if s in ("OD", "R") else "OS"
    return s


def row_key(r, id_col, eye_col):
    return (str(r[id_col]).strip(), norm_eye(r.get(eye_col, "OD")))


def load_and_merge(file_paths, out_path):
    """
    Merge Excel files: for each file in order, drop from current result any row
    whose (ID, Eye) appears in this file, then append this file's rows.
    So later file wins for duplicate (ID, Eye).
    """
    merged = None
    id_col = None
    eye_col = None

    for path in file_paths:
        path = Path(path)
        if not path.exists():
            print(f"Skip (not found): {path}")
            continue
        df = pd.read_excel(path, sheet_name=0)
        if df.empty:
            print(f"Skip (empty): {path}")
            continue

        cid = find_id_col(df)
        ceye = find_eye_col(df)
        if ceye is None:
            ceye = "Eye" if "Eye" in df.columns else (df.columns[2] if len(df.columns) > 2 else df.columns[0])

        if merged is None:
            merged = df.copy()
            id_col = cid
            eye_col = ceye
            print(f"Load: {path.name} -> {len(merged)} rows")
            continue

        new_keys = set(df.apply(lambda r: row_key(r, cid, ceye), axis=1))
        keep = ~merged.apply(lambda r: row_key(r, id_col, eye_col) in new_keys, axis=1)
        n_drop = (~keep).sum()
        merged = pd.concat([merged.loc[keep], df], ignore_index=True)
        print(f"Merge: {path.name} (drop {n_drop} duplicates, add {len(df)}) -> total {len(merged)}")

    if merged is None:
        print("No data loaded. Check that at least one file exists.")
        return False

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_excel(out_path, index=False)
    print(f"Saved: {out_path} ({len(merged)} rows)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Merge Kane result Excel files by (ID, Eye); later file overwrites.")
    parser.add_argument(
        "--files",
        nargs="+",
        default=None,
        help="Excel paths to merge (default: Kane_results.xlsx + two kane_missing_*.xlsx)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output path (default: batch_calculators/Kane_results.xlsx)",
    )
    args = parser.parse_args()

    file_paths = args.files if args.files else DEFAULT_FILES
    out_path = args.output
    if out_path is None:
        out_path = BASE / "batch_calculators" / "Kane_results.xlsx"
    else:
        out_path = Path(args.output)
        if not out_path.is_absolute():
            out_path = BASE / out_path

    load_and_merge(file_paths, out_path)


if __name__ == "__main__":
    main()
