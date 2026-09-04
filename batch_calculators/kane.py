"""
Fill Kane Formula IOL Calculator (https://www.iolformula.com/) with patient and
biometry data from "Yang Ning" xlsx. Uses Playwright for browser automation.

Kane needs: Surgeon, Patient, ID, Sex (M/F), and per-eye: A-Constant, Target refraction,
AL, K1, K2, ACD; optional LT, CCT. We fill one eye per row (OD or OS from column).

Requirements:
  pip install playwright pandas openpyxl
  playwright install chromium

Usage:
  python kane.py    # run Excel batch (USE_XLSX_TEST=True). XLSX_N_ROWS=None = all rows.
  python kane.py    # or single config (USE_XLSX_TEST=False)
  Output: Kane_results.xlsx with Row_Index, ID, Eye, Kane_Recommended_IOL, Kane_IOL_Table.
"""

import re
import time
import pandas as pd
from playwright.sync_api import sync_playwright

# --- Test: Excel batch ---
USE_XLSX_TEST = True
XLSX_PATH = "杨宁整合四文件合并_填补后.xlsx"
XLSX_N_ROWS = None   # None or 0 = all rows; positive int = first N rows
KANE_OUTPUT_PATH = "Kane_results.xlsx"

# --- Config when USE_XLSX_TEST=False ---
SURGEON = "Dr. Smith"
PATIENT = {"id": "2025001", "name": "John Doe", "sex": "M"}
OD = {
    "target_refr": "0.00",
    "al": "23.5",
    "k1": "43.5",
    "k2": "44.0",
    "acd": "3.0",
    "lt": "4.5",
    "cct": "550",
    "a_constant": "118.4",
}
OS = {
    "target_refr": "0.00",
    "al": "23.4",
    "k1": "43.5",
    "k2": "44.0",
    "acd": "3.0",
    "lt": "4.5",
    "cct": "548",
    "a_constant": "118.4",
}

HEADLESS = True
KANE_URL = "https://www.iolformula.com/"

# Timeout (ms) for page load and actions; on timeout skip that sample and continue
KANE_PAGE_TIMEOUT_MS = 20000

# Kane Formula allowed ranges (skip row if outside)
KANE_AL_MIN, KANE_AL_MAX = 18.0, 35.0       # mm
KANE_K1_MIN, KANE_K1_MAX = 30.0, 65.0       # D
KANE_K2_MIN, KANE_K2_MAX = 30.0, 65.0       # D
KANE_ACD_MIN, KANE_ACD_MAX = 1.50, 5.00     # mm
KANE_LT_MIN, KANE_LT_MAX = 2.50, 8.00       # mm (optional)
KANE_CCT_MIN, KANE_CCT_MAX = 350, 650       # um (optional)


def _eye_loc(loc, side):
    """Return .first for OD, .nth(1) for OS."""
    return loc.first if side == "od" else loc.nth(1)


def load_and_validate_rows(path, n):
    """
    Load first n rows from Excel. Validate and clean for Kane.
    Kane requires: AL, K1, K2, ACD, A_Constant, 眼别, Gender, ID.
    Optional: 预留 (default 0), LT, CCT. LT<1: if 0.1<LT<1 treated as cm (LT*10); else skip.
    CCT<100: *1000. Ranges (skip if outside): AL 18-35 mm, K1/K2 30-65 D, ACD 1.5-5 mm,
    LT 2.5-8 mm, CCT 350-650 um.
    Returns list of {patient, eye_side, eye_data, a_constant, row_index}.
    """
    df = pd.read_excel(path, sheet_name=0)
    out = []
    limit = len(df) if (n is None or n <= 0) else min(int(n), len(df))
    for i in range(limit):
        r = df.iloc[i]
        al = r.get("AL", r.get("al"))
        acd = r.get("ACD", r.get("acd"))
        k1 = r.get("K1", r.get("k1"))
        k2 = r.get("K2", r.get("k2"))
        a_const = r.get("A_Constant", r.get("a_constant"))
        eye = str(r.get("眼别", "OD")).strip().upper()
        if eye not in ("OD", "OS"):
            print(f"  [skip row {i+1}] eye not OD/OS: {eye}")
            continue
        if pd.isna(al) or pd.isna(k1) or pd.isna(k2) or pd.isna(acd) or pd.isna(a_const):
            print(f"  [skip row {i+1}] AL/K1/K2/ACD/A_Constant missing")
            continue
        al_f = float(al)
        if not (KANE_AL_MIN <= al_f <= KANE_AL_MAX):
            print(f"  [skip row {i+1}] AL={al_f} out of range [{KANE_AL_MIN}-{KANE_AL_MAX}] mm")
            continue
        k1_f = float(k1)
        if not (KANE_K1_MIN <= k1_f <= KANE_K1_MAX):
            print(f"  [skip row {i+1}] K1={k1_f} out of range [{KANE_K1_MIN}-{KANE_K1_MAX}] D")
            continue
        k2_f = float(k2)
        if not (KANE_K2_MIN <= k2_f <= KANE_K2_MAX):
            print(f"  [skip row {i+1}] K2={k2_f} out of range [{KANE_K2_MIN}-{KANE_K2_MAX}] D")
            continue
        acd_f = float(acd)
        if not (KANE_ACD_MIN <= acd_f <= KANE_ACD_MAX):
            print(f"  [skip row {i+1}] ACD={acd_f} out of range [{KANE_ACD_MIN}-{KANE_ACD_MAX}] mm")
            continue
        lt = r.get("LT", r.get("lt"))
        if not pd.isna(lt):
            lt = float(lt)
            if lt < 1:
                if 0.1 < lt < 1:
                    lt = lt * 10
                else:
                    print(f"  [skip row {i+1}] LT<1 (={lt}), skip")
                    continue
            if not (KANE_LT_MIN <= lt <= KANE_LT_MAX):
                print(f"  [skip row {i+1}] LT={lt:.2f} out of range [{KANE_LT_MIN}-{KANE_LT_MAX}] mm")
                continue
            lt = f"{lt:.2f}"
        else:
            lt = None
        cct = r.get("CCT", r.get("cct"))
        if not pd.isna(cct):
            cct = float(cct)
            if cct < 100:
                cct = cct * 1000
            cct = int(round(cct))
            if not (KANE_CCT_MIN <= cct <= KANE_CCT_MAX):
                print(f"  [skip row {i+1}] CCT={cct} out of range [{KANE_CCT_MIN}-{KANE_CCT_MAX}] um")
                continue
            cct = str(cct)
        else:
            cct = None
        target = r.get("预留", r.get("target", 0.0))
        if pd.isna(target):
            target = 0.0
        target = float(target)
        pid = r.get("ID", "unknown")
        if pd.isna(pid):
            pid = "unknown"
        pid = str(pid).strip()
        g = r.get("Gender", "Not provided")
        if pd.isna(g) or str(g).strip() == "":
            sex = "M"
        else:
            sex = "F" if str(g).strip().lower().startswith("f") else "M"
        patient = {"id": pid, "name": pid[:24] if len(pid) > 24 else pid, "sex": sex}
        eye_data = {
            "target_refr": f"{target:.2f}",
            "al": f"{al_f:.2f}",
            "k1": f"{k1_f:.2f}",
            "k2": f"{k2_f:.2f}",
            "acd": f"{acd_f:.2f}",
            "lt": lt,
            "cct": cct,
        }
        out.append({
            "patient": patient,
            "eye_side": eye.lower(),
            "eye_data": eye_data,
            "a_constant": f"{float(a_const):.2f}",
            "row_index": i + 1,
        })
    return out


def _agree_if_present(page):
    """Click 'I Agree' if terms are shown."""
    try:
        btn = page.get_by_text("I Agree", exact=True)
        btn.wait_for(state="visible", timeout=5000)
        btn.click()
        time.sleep(2)
    except Exception:
        pass


def _fill_kane_form(page, row, surgeon):
    """Fill Kane form for one row: patient, sex, one eye (OD or OS)."""
    p = row["patient"]
    side = row["eye_side"]
    ed = row["eye_data"]
    ac = row["a_constant"]

    # Surgeon, Patient, ID
    page.get_by_label("Surgeon").fill(surgeon)
    page.get_by_label("Patient").fill(p["name"])
    page.get_by_label("ID").fill(p["id"])

    # Sex: M or F. Click the label/region (checkbox can be intercepted)
    if p["sex"] == "M":
        page.get_by_text("M", exact=True).first.click()
    else:
        page.get_by_text("F", exact=True).first.click()
    time.sleep(0.2)

    # One-eye block: A-Constant, Target, AL, K1, K2, ACD, [LT], [CCT]
    aconst = page.get_by_label("A-Constant")
    _eye_loc(aconst, side).fill(ac)

    tr = page.get_by_label("Target refraction")
    _eye_loc(tr, side).fill(ed["target_refr"])

    # AL, K1, K2, ACD: placeholder/name often like "AL (18.0 - 35.0 mm)"
    al = page.get_by_role("textbox", name=re.compile(r"AL\s*\(18", re.I))
    _eye_loc(al, side).fill(ed["al"])
    k1 = page.get_by_role("textbox", name=re.compile(r"K1\s*\(30", re.I))
    _eye_loc(k1, side).fill(ed["k1"])
    k2 = page.get_by_role("textbox", name=re.compile(r"K2\s*\(30", re.I))
    _eye_loc(k2, side).fill(ed["k2"])
    acd = page.get_by_role("textbox", name=re.compile(r"ACD\s*\(1", re.I))
    _eye_loc(acd, side).fill(ed["acd"])

    if ed.get("lt"):
        lt = page.get_by_role("textbox", name=re.compile(r"LT\s*\(2", re.I))
        _eye_loc(lt, side).fill(ed["lt"])
    if ed.get("cct"):
        cct = page.get_by_role("textbox", name=re.compile(r"CCT\s*\(3", re.I))
        _eye_loc(cct, side).fill(ed["cct"])


def _extract_iol_table(page):
    """
    After Calculate, wait for 'Processing...' to disappear, then parse the
    IOL Power (D) vs Refraction (D) table. Returns list of (power, refraction).
    """
    try:
        page.get_by_text("Processing...").wait_for(state="hidden", timeout=90000)
    except Exception:
        pass
    time.sleep(2)
    out = []
    try:
        tbl = page.get_by_role("table").filter(
            has=page.get_by_role("columnheader", name=re.compile(r"IOL\s*Power", re.I))
        )
        tbl.wait_for(state="visible", timeout=30000)
        rows = tbl.get_by_role("row").all()
        for r in rows[1:]:
            cells = r.get_by_role("cell").all()
            if len(cells) >= 2:
                out.append((cells[0].inner_text().strip(), cells[1].inner_text().strip()))
    except Exception as e:
        print(f"  [warn] Could not extract IOL table: {e}")
    return out


def run_xlsx_test(input_path=None, output_path=None):
    """Load rows from Excel. For each: goto/agree (row 0 only), fill, Calculate,
    wait for completion, extract IOL table, click New patient. Save all results to Excel.
    If input_path/output_path are given, use them; else use XLSX_PATH and KANE_OUTPUT_PATH."""
    xlsx_path = input_path if input_path is not None else XLSX_PATH
    out_path = output_path if output_path is not None else KANE_OUTPUT_PATH
    rows = load_and_validate_rows(xlsx_path, XLSX_N_ROWS)
    if not rows:
        print("No valid rows from Excel. Nothing to run.")
        return
    n_info = "all" if (XLSX_N_ROWS is None or XLSX_N_ROWS <= 0) else f"first {XLSX_N_ROWS}"
    print(f"Running Kane for {len(rows)} row(s) from {xlsx_path} ({n_info} rows, after validation).")
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(KANE_PAGE_TIMEOUT_MS)
        page_ok = False
        for i, row in enumerate(rows):
            pid = row["patient"]["id"]
            side = row["eye_side"].upper()
            print(f"\n--- Row {row['row_index']} ({pid} {side}) ---")
            # Load page when first row or previous row failed
            if not page_ok or i == 0:
                try:
                    page.goto(KANE_URL, wait_until="load", timeout=KANE_PAGE_TIMEOUT_MS)
                    time.sleep(1)
                    _agree_if_present(page)
                    time.sleep(1)
                    page_ok = True
                except Exception as e:
                    print(f"  [skip] page load timeout or error: {e}")
                    results.append({
                        "Row_Index": row["row_index"],
                        "ID": pid,
                        "Eye": side,
                        "Kane_Recommended_IOL": "",
                        "Kane_IOL_Table": "",
                    })
                    pd.DataFrame(results).to_excel(out_path, index=False)
                    page_ok = False
                    continue
            try:
                try:
                    page.get_by_label("Surgeon").wait_for(state="visible", timeout=10000)
                except Exception:
                    pass
                _fill_kane_form(page, row, SURGEON)
                time.sleep(0.3)
                calc_btn = page.get_by_role("button", name="Calculate")
                calc_btn.scroll_into_view_if_needed()
                calc_btn.click()
                table = _extract_iol_table(page)
                table_str = ""
                rec_iol = ""
                if table:
                    print("  IOL Power (D) | Refraction (D)")
                    for pw, ref in table:
                        print(f"    {pw}  |  {ref}")
                    table_str = "; ".join(f"{p}:{r}" for p, r in table)
                    target = float(row["eye_data"]["target_refr"])
                    try:
                        best = min(table, key=lambda pr: abs(float(pr[1]) - target))
                        rec_iol = str(best[0])
                    except Exception:
                        pass
                else:
                    print("  (no IOL table extracted)")
                results.append({
                    "Row_Index": row["row_index"],
                    "ID": pid,
                    "Eye": side,
                    "Kane_Recommended_IOL": rec_iol,
                    "Kane_IOL_Table": table_str,
                })
                try:
                    new_btn = page.get_by_role("button", name="New patient")
                    new_btn.scroll_into_view_if_needed()
                    new_btn.click()
                    time.sleep(1.5)
                except Exception:
                    pass
                page_ok = True
            except Exception as e:
                print(f"  [skip] timeout or error: {e}")
                results.append({
                    "Row_Index": row["row_index"],
                    "ID": pid,
                    "Eye": side,
                    "Kane_Recommended_IOL": "",
                    "Kane_IOL_Table": "",
                })
                page_ok = False
                try:
                    page.get_by_role("button", name="New patient").click(timeout=3000)
                    time.sleep(1)
                except Exception:
                    pass
            pd.DataFrame(results).to_excel(out_path, index=False)
        browser.close()
    print(f"\nResults saved to {out_path}")
    print("Done.")


def run():
    """Single run with built-in OD/OS config (both eyes)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context()
        page = context.new_page()
        page.goto(KANE_URL, wait_until="load")
        time.sleep(1)
        _agree_if_present(page)
        time.sleep(1)
        page.get_by_label("Surgeon").fill(SURGEON)
        page.get_by_label("Patient").fill(PATIENT["name"])
        page.get_by_label("ID").fill(PATIENT["id"])
        if PATIENT["sex"] == "M":
            page.get_by_text("M", exact=True).first.click()
        else:
            page.get_by_text("F", exact=True).first.click()
        time.sleep(0.2)
        # OD
        page.get_by_label("A-Constant").first.fill(OD["a_constant"])
        page.get_by_label("Target refraction").first.fill(OD["target_refr"])
        page.get_by_role("textbox", name=re.compile(r"AL\s*\(18", re.I)).first.fill(OD["al"])
        page.get_by_role("textbox", name=re.compile(r"K1\s*\(30", re.I)).first.fill(OD["k1"])
        page.get_by_role("textbox", name=re.compile(r"K2\s*\(30", re.I)).first.fill(OD["k2"])
        page.get_by_role("textbox", name=re.compile(r"ACD\s*\(1", re.I)).first.fill(OD["acd"])
        if OD.get("lt"):
            page.get_by_role("textbox", name=re.compile(r"LT\s*\(2", re.I)).first.fill(OD["lt"])
        if OD.get("cct"):
            page.get_by_role("textbox", name=re.compile(r"CCT\s*\(3", re.I)).first.fill(OD["cct"])
        # OS
        page.get_by_label("A-Constant").nth(1).fill(OS["a_constant"])
        page.get_by_label("Target refraction").nth(1).fill(OS["target_refr"])
        page.get_by_role("textbox", name=re.compile(r"AL\s*\(18", re.I)).nth(1).fill(OS["al"])
        page.get_by_role("textbox", name=re.compile(r"K1\s*\(30", re.I)).nth(1).fill(OS["k1"])
        page.get_by_role("textbox", name=re.compile(r"K2\s*\(30", re.I)).nth(1).fill(OS["k2"])
        page.get_by_role("textbox", name=re.compile(r"ACD\s*\(1", re.I)).nth(1).fill(OS["acd"])
        if OS.get("lt"):
            page.get_by_role("textbox", name=re.compile(r"LT\s*\(2", re.I)).nth(1).fill(OS["lt"])
        if OS.get("cct"):
            page.get_by_role("textbox", name=re.compile(r"CCT\s*\(3", re.I)).nth(1).fill(OS["cct"])
        page.get_by_role("button", name="Calculate").click()
        table = _extract_iol_table(page)
        if table:
            print("OD IOL Power (D) | Refraction (D)")
            for pw, ref in table:
                print(f"  {pw}  |  {ref}")
        try:
            page.get_by_role("button", name="New patient").click()
            time.sleep(1.5)
        except Exception:
            pass
        input("Press Enter to close browser...")
        browser.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Kane IOL batch from Excel")
    parser.add_argument("--input", "-i", type=str, default=None, help="Input Excel path (default: XLSX_PATH)")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output Excel path (default: Kane_results.xlsx)")
    args = parser.parse_args()
    if args.input is not None:
        XLSX_PATH = args.input
    if args.output is not None:
        KANE_OUTPUT_PATH = args.output
    if USE_XLSX_TEST:
        run_xlsx_test(input_path=args.input, output_path=args.output)
    else:
        run()
