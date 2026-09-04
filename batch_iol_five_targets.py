# -*- coding: utf-8 -*-
"""
For each sample: take real reserved refraction (预留), then on the ASCRS *web*
calculator run 7 target refs (预留-1.5, 预留-1, 预留-0.5, 预留, 预留+0.5, 预留+1, 预留+1.5), scrape
the page results, and store the 7 results as one JSON text in a column.

Uses Playwright to fill https://iolcalc.ascrs.org/wbfrmCalculator.aspx and
parse Average IOL Power, Min, Max, and per-formula values from the page.

Single-threaded. Waits are event-driven (wait_for_selector) where possible.

Reads: data/杨宁整合四文件合并_填补后.xlsx
Writes: data/杨宁整合四文件合并_七档目标屈光IOL_网页.json列.xlsx

ACD is clamped to [2.0, 4.0] mm so the calculator does not show "check input in red".
"""

import json
import os
import re
import sys
import time
import pandas as pd
from playwright.sync_api import sync_playwright
from tqdm import tqdm

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
XLSX_PATH = os.path.join(DATA_DIR, "杨宁整合四文件合并_填补后.xlsx")
HAIGIS_JSON_PATH = os.path.join(DATA_DIR, "haigis_constants.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "杨宁整合四文件合并_七档目标屈光IOL_网页.json列.xlsx")
PROGRESS_PATH = os.path.join(DATA_DIR, "杨宁整合四文件合并_七档目标屈光IOL_网页_progress.jsonl")

# Short timeout so stuck samples are skipped quickly (ms)
ACTION_TIMEOUT_MS = 4000

URL = "https://iolcalc.ascrs.org/wbfrmCalculator.aspx"
ACD_MIN = 2.0
ACD_MAX = 4.0
# 7 target refs: reserved + (-1.5, -1, -0.5, 0, +0.5, +1, +1.5)
TARGET_OFFSETS = [-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5]

# Defaults when not in Excel
DEFAULT_LENS_THICK = 4.5
DEFAULT_SF = 1.95
DEFAULT_HAIGIS = (1.6, 0.4, 0.1)


def load_haigis_constants(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    default = data.get("default", {"a0": 1.10, "a1": 0.40, "a2": 0.10})
    lenses = data.get("lenses", {})
    return default, lenses


def get_haigis_abc(row, default, lenses):
    model = row.get("晶体型号", row.get("model"))
    if pd.isna(model) or str(model).strip() == "":
        return DEFAULT_HAIGIS
    key = str(model).strip()
    if key in lenses:
        L = lenses[key]
        return (L["a0"], L["a1"], L["a2"])
    return (default["a0"], default["a1"], default["a2"])


def safe_float(x, default=None):
    if pd.isna(x):
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def clamp_acd(acd):
    if acd is None:
        return ACD_MAX  # use upper bound so Haigis has a value
    return max(ACD_MIN, min(ACD_MAX, float(acd)))


def row_to_form_values(row, target_ref_d, default_haigis, lenses_haigis):
    """Build dict of form field id/name -> value for one row and one target ref."""
    eye = row.get("眼别")
    if pd.isna(eye) or str(eye).strip() == "":
        eye = "OD"
    else:
        eye = str(eye).strip()
    al = safe_float(row.get("AL"))
    k1 = safe_float(row.get("K1"))
    k2 = safe_float(row.get("K2"))
    acd_raw = safe_float(row.get("ACD"))
    acd = clamp_acd(acd_raw)
    wtw = safe_float(row.get("W2W"), 12.0)
    a_const = safe_float(row.get("A_Constant"), 118.5)
    a0, a1, a2 = get_haigis_abc(row, default_haigis, lenses_haigis)
    lt = safe_float(row.get("LT"), DEFAULT_LENS_THICK)
    if lt is not None and (lt < 1 or lt > 6):
        lt = DEFAULT_LENS_THICK

    return {
        "txtDoctorName": "Batch",
        "txtPatientName": str(row.get("ID", "")),
        "txtPatientID": str(row.get("ID", "")),
        "txtEyeLR": eye,
        "txtIOLtype": "SN60WF",
        "txtBioTargetRef": str(target_ref_d),
        "txtPreSph": "0",
        "txtPreCyl": "0",
        "txtPreVer": "12.5",
        "txtPstSph": "0",
        "txtPstCyl": "0",
        "txtPstVer": "12.5",
        "txtBioAL": str(al),
        "txtBioACD": str(acd),
        "LensThickness": str(lt),
        "WTW": str(wtw),
        "txtBioAconst": str(a_const),
        "txtBioSF": str(DEFAULT_SF),
        "txtBioa0": str(a0),
        "txtBioa1": str(a1),
        "txtBioa2": str(a2),
        "txtPreK1": str(k1),
        "txtPreK2": str(k2),
        "txtBioK1": str(k1),
        "txtBioK2": str(k2),
    }


def fill_form_from_dict(page, form_dict):
    """Fill ASCRS form from dict (id -> value and name -> value for K/SF/Haigis)."""
    by_id = ["txtDoctorName", "txtPatientName", "txtPatientID", "txtEyeLR", "txtIOLtype",
             "txtBioTargetRef", "txtPreSph", "txtPreCyl", "txtPreVer", "txtPstSph", "txtPstCyl",
             "txtPstVer", "txtBioAL", "txtBioACD", "LensThickness", "WTW", "txtBioAconst",
             "txtBioSF", "txtBioa0", "txtBioa1", "txtBioa2"]
    by_name = ["txtPreK1", "txtPreK2", "txtBioK1", "txtBioK2", "txtBioSF", "txtBioa0", "txtBioa1", "txtBioa2"]
    for key in by_id:
        if key not in form_dict:
            continue
        try:
            page.locator(f"#{key}").first.fill(str(form_dict[key]), timeout=ACTION_TIMEOUT_MS)
        except Exception:
            pass
    for name in by_name:
        if name not in form_dict:
            continue
        try:
            page.locator(f"input[name='{name}']").first.fill(str(form_dict[name]), timeout=ACTION_TIMEOUT_MS)
        except Exception:
            pass


def click_calculate(page):
    # Short timeout so stuck samples are skipped quickly.
    page.get_by_role("button", name="Calculate").click(no_wait_after=True, timeout=ACTION_TIMEOUT_MS)
    try:
        page.wait_for_selector(
            "text=Average IOL Power (All Available Formulas):",
            timeout=ACTION_TIMEOUT_MS
        )
        return True
    except Exception:
        return False


# Only these three formulas are stored in the 7-run JSON output
FORMULAS_KEEP = ("Shammas_D", "Haigis_L_D", "Barrett_True_K_D")


def parse_results(page):
    """Extract from page: Shammas, Haigis-L, Barrett True K only."""
    full_text = page.locator("body").inner_text(timeout=ACTION_TIMEOUT_MS)
    result = {}
    for name, pattern in [
        ("Barrett_True_K_D", r"Barrett True K\s+([-\d.]+)\s*D"),
        ("Shammas_D", r"Shammas\s+([-\d.]+)\s*D"),
        ("Haigis_L_D", r"Haigis-L\s+([-\d.]+)\s*D"),
    ]:
        m = re.search(pattern, full_text)
        if m:
            result[name] = m.group(1)
    return result


def run_one_sample_five_targets(page, row, default_haigis, lenses_haigis):
    """
    For one row: 7 target refs = 预留 + [-1.5, -1, -0.5, 0, +0.5, +1, +1.5].
    Return list of 7 dicts from webpage (each has target_ref_D, average_iol_D, min_iol_D, max_iol_D, ...).
    If 预留 or required biometry missing, return None.
    """
    reserved = safe_float(row.get("预留"))
    if reserved is None:
        return None
    al = safe_float(row.get("AL"))
    k1 = safe_float(row.get("K1"))
    k2 = safe_float(row.get("K2"))
    a_const = safe_float(row.get("A_Constant"))
    if al is None or k1 is None or k2 is None or a_const is None:
        return None

    results = []
    for offset in TARGET_OFFSETS:
        target_ref = round(reserved + offset, 2)
        form_dict = row_to_form_values(row, target_ref, default_haigis, lenses_haigis)
        fill_form_from_dict(page, form_dict)
        got_result = click_calculate(page)
        parsed = parse_results(page)
        rec = {
            "target_ref_D": target_ref,
            "目标屈光度": target_ref,
            "Shammas_IOL_D": parsed.get("Shammas_D"),
            "Haigis_L_IOL_D": parsed.get("Haigis_L_D"),
            "Barrett_True_K_IOL_D": parsed.get("Barrett_True_K_D"),
        }
        if not got_result:
            rec["_page_error"] = "no_result_table"
        results.append(rec)

    return results


def run(max_rows=None):
    if not os.path.isfile(XLSX_PATH):
        print(f"Input file not found: {XLSX_PATH}")
        return
    if not os.path.isfile(HAIGIS_JSON_PATH):
        print(f"Haigis constants not found: {HAIGIS_JSON_PATH}")
        return

    default_haigis, lenses_haigis = load_haigis_constants(HAIGIS_JSON_PATH)
    df = pd.read_excel(XLSX_PATH, sheet_name=0)
    n = len(df)
    if max_rows is not None:
        n = min(n, max_rows)
        print(f"Limiting to first {n} rows (max_rows={max_rows})")

    json_col = [None] * len(df)

    # Load previous progress so we have partial results if resuming
    if os.path.isfile(PROGRESS_PATH):
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    idx = int(rec["i"])
                    if 0 <= idx < len(json_col):
                        json_col[idx] = rec["json"]
                except Exception:
                    pass
        prev_count = sum(1 for v in json_col if v is not None)
        print(f"Resumed: {prev_count} rows from {PROGRESS_PATH}")

    progress_file = open(PROGRESS_PATH, "a", encoding="utf-8")
    use_tqdm = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    if use_tqdm:
        pbar = tqdm(range(n), desc="Samples", unit="row", ncols=80)
        it = pbar
    else:
        pbar = None
        it = range(n)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            try:
                page.goto(URL, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_selector("#btnCalculate", timeout=15000)
            except Exception as e:
                print(f"Failed to load page: {e}")
                browser.close()
                progress_file.close()
                return
            page.set_default_timeout(ACTION_TIMEOUT_MS)
            try:
                for i in it:
                    row = df.iloc[i]
                    if json_col[i] is not None:
                        if pbar is not None:
                            pbar.set_postfix(id=str(row.get("ID", "")))
                        continue
                    try:
                        results = run_one_sample_five_targets(page, row, default_haigis, lenses_haigis)
                        if results is not None:
                            json_str = json.dumps(results, ensure_ascii=False)
                            json_col[i] = json_str
                            progress_file.write(json.dumps({"i": i, "id": str(row.get("ID", "")), "json": json_str}, ensure_ascii=False) + "\n")
                            progress_file.flush()
                    except Exception as e:
                        msg = f"Skipped row {i + 1} ID={row.get('ID', '')}: {e}"
                        (tqdm.write(msg) if pbar else print(msg))
                    if pbar is not None:
                        pbar.set_postfix(id=str(row.get("ID", "")))
                    else:
                        if (i + 1) % 20 == 0 or i == 0:
                            print(f"Progress: {i + 1}/{n} (ID={row.get('ID', '')})")
            finally:
                browser.close()
    finally:
        progress_file.close()

    if pbar is not None:
        pbar.close()
    df["IOL_calc_7targets_web_json"] = json_col
    df.to_excel(OUTPUT_PATH, index=False)
    print(f"Done. Output: {OUTPUT_PATH}")
    valid = sum(1 for v in json_col if v is not None)
    print(f"Rows with valid JSON: {valid}")


if __name__ == "__main__":
    import sys
    max_rows = None
    if len(sys.argv) > 1:
        try:
            max_rows = int(sys.argv[1])
        except ValueError:
            pass
    run(max_rows=max_rows)
