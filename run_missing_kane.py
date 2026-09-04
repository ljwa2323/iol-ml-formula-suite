# -*- coding: utf-8 -*-
"""
1) Build a temp Excel with only rows whose (ID, Eye) are in missing_kane_ids.txt.
2) Call batch_calculators/kane.py; output is saved to a timestamped file first (no data loss).
3) After run completes, merge that file into batch_calculators/Kane_results.xlsx.

Run from project root:
  python run_missing_kane.py
  python run_missing_kane.py --missing-ids kane_retry_ids.txt   # retry specific IDs only
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
BATCH_DIR = BASE / "batch_calculators"
FILL_PATH = DATA_DIR / "杨宁整合四文件合并_填补后.xlsx"
DEFAULT_MISSING_IDS_PATH = BASE / "missing_kane_ids.txt"
KANE_RESULTS_PATH = BATCH_DIR / "Kane_results.xlsx"
TEMP_INPUT_PATH = DATA_DIR / "temp_missing_kane_input.xlsx"
KANE_SCRIPT = BATCH_DIR / "kane.py"


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
    parser = argparse.ArgumentParser(description="Run Kane for missing (ID, Eye) only, then merge into Kane_results.xlsx")
    parser.add_argument("--missing-ids", type=str, default=None,
                        help=f"Path to missing IDs file (default: {DEFAULT_MISSING_IDS_PATH.name})")
    args = parser.parse_args()
    missing_ids_path = Path(args.missing_ids) if args.missing_ids else DEFAULT_MISSING_IDS_PATH
    if not missing_ids_path.is_absolute():
        missing_ids_path = BASE / missing_ids_path

    if not FILL_PATH.exists():
        print(f"Fill file not found: {FILL_PATH}")
        sys.exit(1)
    if not missing_ids_path.exists():
        print(f"Missing IDs file not found: {missing_ids_path}")
        sys.exit(1)
    if not KANE_SCRIPT.exists():
        print(f"Kane script not found: {KANE_SCRIPT}")
        sys.exit(1)

    missing_keys = load_missing_keys(missing_ids_path)
    print(f"Missing (ID, Eye) count: {len(missing_keys)}")
    if not missing_keys:
        print("No missing samples. Nothing to run.")
        return

    df_fill = pd.read_excel(FILL_PATH, sheet_name=0)
    id_col = find_id_col(df_fill)
    eye_col = find_eye_col(df_fill)
    if eye_col is None:
        print("Fill file has no eye column (e.g. 眼别). Abort.")
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
    run_output_path = DATA_DIR / f"kane_missing_{timestamp}.xlsx"
    cmd = [
        sys.executable,
        str(KANE_SCRIPT),
        "--input", str(TEMP_INPUT_PATH),
        "--output", str(run_output_path),
    ]
    print(f"Running: {' '.join(cmd)}")
    print(f"Results will be saved to: {run_output_path}")
    ret = subprocess.run(cmd, cwd=str(BASE))
    if ret.returncode != 0:
        print("Kane script failed. If partial output exists, it is at:", run_output_path)
        print("You can merge it manually later. Abort.")
        sys.exit(ret.returncode)
    if not run_output_path.exists():
        print("Kane did not produce output file. Abort.")
        sys.exit(1)
    print(f"Run output saved: {run_output_path}")

    # Merge into main results (run output already saved above)
    df_new = pd.read_excel(run_output_path, sheet_name=0)
    new_keys = set(zip(df_new["ID"].astype(str).str.strip(), df_new["Eye"].astype(str).str.strip().str.upper()))
    if KANE_RESULTS_PATH.exists():
        df_existing = pd.read_excel(KANE_RESULTS_PATH, sheet_name=0)
        id_col = find_id_col(df_existing)
        eye_col = find_eye_col(df_existing)
        if eye_col is None or eye_col not in df_existing.columns:
            eye_col = "Eye" if "Eye" in df_existing.columns else df_existing.columns[2]
        keep = ~df_existing.apply(lambda r: (str(r[id_col]).strip(), norm_eye(r.get(eye_col, "OD"))) in new_keys, axis=1)
        df_rest = df_existing.loc[keep]
        df_merged = pd.concat([df_rest, df_new], ignore_index=True)
        print(f"Merged: kept {len(df_rest)} existing (no overlap), added {len(df_new)} new -> total {len(df_merged)}")
    else:
        df_merged = df_new
        print(f"No existing Kane_results; using {len(df_merged)} new rows")
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    df_merged.to_excel(KANE_RESULTS_PATH, index=False)
    print(f"Merged into: {KANE_RESULTS_PATH}")
    print(f"Run output kept at: {run_output_path}")
    print("Done.")


if __name__ == "__main__":
    main()
