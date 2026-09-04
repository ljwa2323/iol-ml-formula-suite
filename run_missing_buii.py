# -*- coding: utf-8 -*-
"""
1) Build a temp Excel with only rows whose (ID, Eye) are in missing_calc_ids.txt.
2) Call batch_calculators/buii.py; output is saved to a timestamped file first (no data loss).
3) After run completes, merge that file into data/杨宁整合四文件合并_计算结果.xlsx.

Run from project root:
  python run_missing_buii.py
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
BATCH_DIR = BASE / "batch_calculators"
FILL_PATH = DATA_DIR / "杨宁整合四文件合并_填补后.xlsx"
MISSING_IDS_PATH = BASE / "missing_calc_ids.txt"
CALC_RESULTS_PATH = DATA_DIR / "杨宁整合四文件合并_计算结果.xlsx"
TEMP_INPUT_PATH = DATA_DIR / "temp_missing_buii_input.xlsx"
BUII_SCRIPT = BATCH_DIR / "buii.py"


def load_missing_keys(path):
    out = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                out.add((parts[0].strip(), parts[1].strip().upper()))
    return out


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


def main():
    if not FILL_PATH.exists():
        print(f"Fill file not found: {FILL_PATH}")
        sys.exit(1)
    if not MISSING_IDS_PATH.exists():
        print(f"Missing IDs file not found: {MISSING_IDS_PATH}")
        sys.exit(1)
    if not BUII_SCRIPT.exists():
        print(f"BUII script not found: {BUII_SCRIPT}")
        sys.exit(1)

    missing_keys = load_missing_keys(MISSING_IDS_PATH)
    print(f"Missing (ID, Eye) count: {len(missing_keys)}")
    if not missing_keys:
        print("No missing samples. Nothing to run.")
        return

    df_fill = pd.read_excel(FILL_PATH, sheet_name=0)
    id_col = find_id_col(df_fill)
    eye_col = find_eye_col(df_fill)
    if eye_col is None:
        print("Fill file has no eye column. Abort.")
        sys.exit(1)

    mask = df_fill.apply(
        lambda r: (str(r[id_col]).strip(), norm_eye(r[eye_col])) in missing_keys,
        axis=1
    )
    df_missing = df_fill.loc[mask].reset_index(drop=True)
    print(f"Rows in fill file for missing (ID, Eye): {len(df_missing)}")
    if df_missing.empty:
        print("No matching rows in fill file. Abort.")
        sys.exit(1)

    TEMP_INPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df_missing.to_excel(TEMP_INPUT_PATH, index=False)
    print(f"Wrote temp input: {TEMP_INPUT_PATH}")

    # Output to timestamped file first so data is never lost (merge later)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_output_path = DATA_DIR / f"buii_missing_{timestamp}.xlsx"
    cmd = [
        sys.executable,
        str(BUII_SCRIPT),
        "--input", str(TEMP_INPUT_PATH),
        "--output", str(run_output_path),
    ]
    print(f"Running: {' '.join(cmd)}")
    print(f"Results will be saved to: {run_output_path}")
    ret = subprocess.run(cmd, cwd=str(BASE))
    if ret.returncode != 0:
        print("BUII script failed. If partial output exists, it is at:", run_output_path)
        print("You can merge it manually later. Abort.")
        sys.exit(ret.returncode)
    if not run_output_path.exists():
        print("BUII did not produce output file. Abort.")
        sys.exit(1)
    print(f"Run output saved: {run_output_path}")

    df_new = pd.read_excel(run_output_path, sheet_name=0)
    id_col_n = find_id_col(df_new)
    eye_col_n = find_eye_col(df_new)
    if eye_col_n is None or eye_col_n not in df_new.columns:
        eye_col_n = "眼别" if "眼别" in df_new.columns else "Eye"
    new_keys = set(zip(df_new[id_col_n].astype(str).str.strip(), df_new[eye_col_n].apply(norm_eye)))
    if CALC_RESULTS_PATH.exists():
        df_existing = pd.read_excel(CALC_RESULTS_PATH, sheet_name=0)
        id_col_e = find_id_col(df_existing)
        eye_col_e = find_eye_col(df_existing)
        if eye_col_e is None or eye_col_e not in df_existing.columns:
            eye_col_e = "眼别" if "眼别" in df_existing.columns else "Eye"
        keep = ~df_existing.apply(lambda r: (str(r[id_col_e]).strip(), norm_eye(r.get(eye_col_e, "OD"))) in new_keys, axis=1)
        df_rest = df_existing.loc[keep]
        df_merged = pd.concat([df_rest, df_new], ignore_index=True)
        print(f"Merged: kept {len(df_rest)} existing (no overlap), added {len(df_new)} new -> total {len(df_merged)}")
    else:
        df_merged = df_new
        print(f"No existing calc results; using {len(df_merged)} new rows")
    df_merged.to_excel(CALC_RESULTS_PATH, index=False)
    print(f"Merged into: {CALC_RESULTS_PATH}")
    print(f"Run output kept at: {run_output_path}")
    print("Done.")


if __name__ == "__main__":
    main()
