# -*- coding: utf-8 -*-
"""
Predicted postoperative SE from actual implanted IOL using SRK/T, Holladay 1, Haigis.
Reads data from data/杨宁整合四文件合并_填补后.xlsx; for each row uses column IOL (actual implanted power)
and appends only: SRKT_SE_pred_actualIOL, Holladay1_SE_pred_actualIOL, Haigis_SE_pred_actualIOL.
Saves to data/杨宁整合四文件合并_公式计算结果.xlsx.

Required columns: AL, K1, K2, A_Constant, IOL; Haigis also needs ACD.
Optional: 晶体型号 (for Haigis lens constants). Holladay 1 uses SF=1.5. K = (K1+K2)/2.

Usage (from project root):
  python batch_iol_formulas.py
"""

import json
import os
import pandas as pd

from iol_formulas import (
    average_K,
    haigis_se_pred,
    holladay1_se_pred,
    srkt_se_pred,
)

# Paths (run from project root)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
XLSX_PATH = os.path.join(DATA_DIR, "杨宁整合四文件合并_填补后.xlsx")
HAIGIS_JSON_PATH = os.path.join(DATA_DIR, "haigis_constants.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "杨宁整合四文件合并_公式计算结果.xlsx")

# Holladay 1 Surgeon Factor (mm)
HOLLADAY_SF = 1.5


def load_haigis_constants(path):
    """Load haigis_constants.json; return (default_dict, lenses_dict)."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    default = data.get("default", {"a0": 1.10, "a1": 0.40, "a2": 0.10})
    lenses = data.get("lenses", {})
    return default, lenses


def get_haigis_abc(row, default, lenses):
    """Get a0, a1, a2 for this row: from lens model (晶体型号) or default."""
    model = row.get("晶体型号", row.get("model"))
    if pd.isna(model) or str(model).strip() == "":
        return default["a0"], default["a1"], default["a2"]
    key = str(model).strip()
    if key in lenses:
        L = lenses[key]
        return L["a0"], L["a1"], L["a2"]
    return default["a0"], default["a1"], default["a2"]


def safe_float(x, default=None):
    """Convert to float; return default if NaN or invalid."""
    if pd.isna(x):
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def run():
    if not os.path.isfile(XLSX_PATH):
        print(f"Input file not found: {XLSX_PATH}")
        return
    if not os.path.isfile(HAIGIS_JSON_PATH):
        print(f"Haigis constants not found: {HAIGIS_JSON_PATH}")
        return

    default_haigis, lenses_haigis = load_haigis_constants(HAIGIS_JSON_PATH)
    df = pd.read_excel(XLSX_PATH, sheet_name=0)

    n = len(df)
    srkt_se_actual_list = [None] * n
    holladay_se_actual_list = [None] * n
    haigis_se_actual_list = [None] * n

    for i in range(n):
        r = df.iloc[i]
        al = safe_float(r.get("AL", r.get("al")))
        k1 = safe_float(r.get("K1", r.get("k1")))
        k2 = safe_float(r.get("K2", r.get("k2")))
        a_const = safe_float(r.get("A_Constant", r.get("a_constant")))
        acd = safe_float(r.get("ACD", r.get("acd")))
        actual_iol = safe_float(r.get("IOL", r.get("iol")))

        if al is None or k1 is None or k2 is None or a_const is None or actual_iol is None:
            continue

        K = average_K(k1, k2)

        # SRK/T: predicted SE for actual implanted IOL
        try:
            srkt_se_actual_list[i] = round(srkt_se_pred(AL=al, K=K, P=actual_iol, A_constant=a_const), 3)
        except (ValueError, ZeroDivisionError):
            pass

        # Holladay 1: predicted SE for actual implanted IOL
        try:
            holladay_se_actual_list[i] = round(holladay1_se_pred(AL=al, K=K, P=actual_iol, SF=HOLLADAY_SF), 3)
        except (ValueError, ZeroDivisionError):
            pass

        # Haigis: predicted SE for actual implanted IOL (needs ACD)
        if acd is not None:
            a0, a1, a2 = get_haigis_abc(r, default_haigis, lenses_haigis)
            try:
                haigis_se_actual_list[i] = round(haigis_se_pred(
                    AL=al, ACD=acd, K=K, P=actual_iol, a0=a0, a1=a1, a2=a2
                ), 3)
            except (ValueError, ZeroDivisionError):
                pass

    df["SRKT_SE_pred_actualIOL"] = srkt_se_actual_list
    df["Holladay1_SE_pred_actualIOL"] = holladay_se_actual_list
    df["Haigis_SE_pred_actualIOL"] = haigis_se_actual_list

    df.to_excel(OUTPUT_PATH, index=False)
    print(f"Done. Output: {OUTPUT_PATH}")
    print(f"Rows: {n}. SRKT_SE_pred_actualIOL, Holladay1_SE_pred_actualIOL, Haigis_SE_pred_actualIOL appended.")


if __name__ == "__main__":
    run()
