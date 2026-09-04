# -*- coding: utf-8 -*-
"""
Merge ID, eye (眼别), and all *_SE_pred_actualIOL columns from multiple Excel files
into 杨宁整合四文件合并_公式计算结果.xlsx.

Source files:
  - data/Kane_results_with_SE_pred.xlsx
  - data/杨宁整合四文件合并_计算结果.xlsx
  - data/杨宁整合四文件合并_填补后_evo_results_alt.xlsx
  - data/杨宁整合四文件合并_七档目标屈光IOL_网页.json列.xlsx

Merge key: (ID, 眼别). Base = 公式计算结果.xlsx. Left join so all base rows kept.

Run from project root:
  python merge_se_pred_into_formula_results.py
  python merge_se_pred_into_formula_results.py -o data/xxx.xlsx
"""

import argparse
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
DEFAULT_BASE = BASE / "data" / "杨宁整合四文件合并_公式计算结果.xlsx"
DEFAULT_SOURCES = [
    BASE / "data" / "Kane_results_with_SE_pred.xlsx",
    BASE / "data" / "杨宁整合四文件合并_计算结果.xlsx",
    BASE / "data" / "杨宁整合四文件合并_填补后_evo_results_alt.xlsx",
    BASE / "data" / "杨宁整合四文件合并_七档目标屈光IOL_网页.json列.xlsx",
]
SUFFIX = "_SE_pred_actualIOL"


def find_id_col(df):
    for c in df.columns:
        s = str(c).strip()
        if s == "ID" or s.lower() == "id":
            return c
    return df.columns[0]


def find_eye_col(df):
    for c in df.columns:
        if "眼别" in str(c) or str(c).strip() in ("Eye", "eye"):
            return c
    return None


def norm_eye(v):
    if pd.isna(v) or str(v).strip() == "":
        return "OD"
    s = str(v).strip().upper()
    if s in ("OD", "OS", "R", "L"):
        return "OD" if s in ("OD", "R") else "OS"
    return s


def get_se_pred_columns(df):
    """Return list of column names ending with _SE_pred_actualIOL."""
    return [c for c in df.columns if str(c).strip().endswith(SUFFIX)]


def main():
    parser = argparse.ArgumentParser(
        description="Merge ID, eye, and *_SE_pred_actualIOL columns from source files into formula results."
    )
    parser.add_argument("-b", "--base", type=str, default=None,
                        help="Base Excel (default: data/杨宁整合四文件合并_公式计算结果.xlsx)")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="Output Excel (default: base dir, stem_merged_SE_pred.xlsx)")
    parser.add_argument("-s", "--sources", type=str, nargs="*", default=None,
                        help="Extra source files (default: Kane, 计算结果, evo_results_alt, 七档目标)")
    args = parser.parse_args()

    base_path = Path(args.base) if args.base else DEFAULT_BASE
    if not base_path.is_absolute():
        base_path = BASE / base_path
    sources = args.sources if args.sources is not None else DEFAULT_SOURCES
    source_paths = [Path(p) if isinstance(p, str) else p for p in sources]
    for i, p in enumerate(source_paths):
        if not p.is_absolute():
            source_paths[i] = BASE / p

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = base_path.parent / (base_path.stem + "_merged_SE_pred" + base_path.suffix)
    if not out_path.is_absolute():
        out_path = BASE / out_path

    if not base_path.exists():
        print(f"Base file not found: {base_path}")
        return

    df = pd.read_excel(base_path, sheet_name=0)
    id_col = find_id_col(df)
    eye_col = find_eye_col(df)
    if eye_col is None:
        eye_col = [c for c in df.columns if "eye" in c.lower() or "眼" in str(c)]
        eye_col = eye_col[0] if eye_col else None
    if eye_col is None:
        print("Base has no eye column (眼别/Eye). Abort.")
        return

    df["_merge_id"] = df[id_col].astype(str).str.strip()
    df["_merge_eye"] = df[eye_col].apply(norm_eye)
    added_any = set()

    for src_path in source_paths:
        if not src_path.exists():
            print(f"Skip (not found): {src_path.name}")
            continue
        src = pd.read_excel(src_path, sheet_name=0)
        if src.empty:
            print(f"Skip (empty): {src_path.name}")
            continue

        sid = find_id_col(src)
        seye = find_eye_col(src)
        if seye is None:
            seye = [c for c in src.columns if "eye" in c.lower() or "眼" in str(c)]
            seye = seye[0] if seye else None
        if seye is None:
            print(f"Skip (no eye col): {src_path.name}")
            continue

        se_cols = get_se_pred_columns(src)
        if not se_cols:
            print(f"Skip (no *{SUFFIX} cols): {src_path.name}")
            continue

        # Only add columns not already in df
        to_add = [c for c in se_cols if c not in df.columns]
        if not to_add:
            print(f"Skip (all SE cols already in base): {src_path.name}")
            continue

        src["_merge_id"] = src[sid].astype(str).str.strip()
        src["_merge_eye"] = src[seye].apply(norm_eye)
        merge_df = src[["_merge_id", "_merge_eye"] + to_add].drop_duplicates(
            subset=["_merge_id", "_merge_eye"], keep="first"
        )
        n_before = len(df)
        df = df.merge(merge_df, on=["_merge_id", "_merge_eye"], how="left")
        assert len(df) == n_before, "merge should not change row count"
        added_any.update(to_add)
        print(f"Merged {src_path.name}: added {to_add}")

    df = df.drop(columns=["_merge_id", "_merge_eye"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_excel(out_path, index=False)
        print(f"Saved: {out_path} (columns added: {sorted(added_any)})")
    except PermissionError:
        alt = out_path.parent / (out_path.stem + "_alt" + out_path.suffix)
        df.to_excel(alt, index=False)
        print(f"Permission denied. Saved to: {alt}")


if __name__ == "__main__":
    main()
