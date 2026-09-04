"""
Batch run ASCRS IOL calculator: set Target Ref (D) from -5 to 5 in steps of 0.5,
click Calculate each time, and collect all results to CSV.
"""

from playwright.sync_api import sync_playwright
import time
import re
import csv
from pathlib import Path

URL = "https://iolcalc.ascrs.org/wbfrmCalculator.aspx"

# Sample biometry (same as second run: Jane Smith, OS)
FORM_DATA = {
    "txtDoctorName": "Dr. Lee",
    "txtPatientName": "Jane Smith",
    "txtPatientID": "002",
    "txtEyeLR": "OS",
    "txtIOLtype": "ZCB00",
    "txtBioTargetRef": "-5",  # will be overwritten in loop
    "txtPreSph": "-6",
    "txtPreCyl": "-0.5",
    "txtPreVer": "12.5",
    "txtPreK1": "43.5",
    "txtPreK2": "44.5",
    "txtPstSph": "-0.25",
    "txtPstCyl": "0",
    "txtPstVer": "12.5",
    "txtBioK1": "37.8",
    "txtBioK2": "38.5",
    "txtBioAL": "24.8",
    "txtBioACD": "2.85",
    "LensThickness": "4.8",
    "WTW": "11.8",
    "txtBioAconst": "119",
    "txtBioSF": "2.0",
    "txtBioa0": "1.55",
    "txtBioa1": "0.4",
    "txtBioa2": "0.1",
}

# name attr for K inputs
FORM_DATA_BY_NAME = {
    "txtPreK1": "43.5",
    "txtPreK2": "44.5",
    "txtBioK1": "37.8",
    "txtBioK2": "38.5",
    "txtBioSF": "2.0",
    "txtBioa0": "1.55",
    "txtBioa1": "0.4",
    "txtBioa2": "0.1",
}


def fill_form(page):
    """Fill all fields once (by id and by name where needed)."""
    for id_or_name, value in FORM_DATA.items():
        try:
            el = page.locator(f"#{id_or_name}").first
            if el.count():
                el.fill(str(value))
        except Exception:
            pass
    for name, value in FORM_DATA_BY_NAME.items():
        try:
            el = page.locator(f"input[name='{name}']").first
            if el.count():
                el.fill(str(value))
        except Exception:
            pass


def set_target_ref(page, target_ref_d):
    """Set only the Target Ref (D) field."""
    page.locator("#txtBioTargetRef").fill(str(target_ref_d))


def click_calculate(page):
    """Click Calculate and wait for results."""
    page.get_by_role("button", name="Calculate").click()
    # Wait for result table (Average IOL Power row to appear/update)
    page.wait_for_selector("text=Average IOL Power (All Available Formulas):", timeout=15000)
    time.sleep(0.5)


def parse_results(page):
    """
    Extract Average IOL Power, Min, Max and optionally per-formula IOL powers.
    Returns dict with keys: target_ref_d, average_iol_d, min_iol_d, max_iol_d, and formula columns.
    """
    result = {}
    # Get all text content from the results area (second big table)
    tables = page.locator("table").all()
    # Usually the result table is the one containing "Average IOL Power"
    full_text = page.locator("body").inner_text()
    # Parse: "Average IOL Power (All Available Formulas): 25.78 D" etc.
    m_avg = re.search(r"Average IOL Power \(All Available Formulas\):\s*([-\d.]+)\s*D", full_text)
    m_min = re.search(r"Min:\s*([-\d.]+)\s*D", full_text)
    m_max = re.search(r"Max:\s*([-\d.]+)\s*D", full_text)
    if m_avg:
        result["average_iol_d"] = m_avg.group(1)
    if m_min:
        result["min_iol_d"] = m_min.group(1)
    if m_max:
        result["max_iol_d"] = m_max.group(1)

    # Optional: parse formula rows (e.g. "Masket Formula 25.88 D", "Shammas 26.36 D", "Haigis-L 25.91 D", "Barrett True K 25.04 D", "Barrett True K No History 25.05 D")
    for name, pattern in [
        ("Masket_Formula", r"Masket Formula\s+([-\d.]+)\s*D"),
        ("Modified_Masket", r"Modified-Masket\s+([-\d.]+)\s*D"),
        ("Barrett_True_K", r"Barrett True K\s+([-\d.]+)\s*D"),
        ("Shammas", r"Shammas\s+([-\d.]+)\s*D"),
        ("Haigis_L", r"Haigis-L\s+([-\d.]+)\s*D"),
        ("Barrett_True_K_No_History", r"Barrett True K No History\s+([-\d.]+)\s*D"),
    ]:
        m = re.search(pattern, full_text)
        if m:
            result[name] = m.group(1)

    return result


def run_batch(output_path=None):
    if output_path is None:
        output_path = Path(__file__).parent / "ascrs_target_ref_results.csv"

    target_refs = [round(-5 + 0.5 * i, 1) for i in range(21)]  # -5, -4.5, ..., 5
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(URL, wait_until="networkidle", timeout=30000)
            time.sleep(1.5)
            fill_form(page)
            time.sleep(0.3)

            for target_ref in target_refs:
                set_target_ref(page, target_ref)
                click_calculate(page)
                parsed = parse_results(page)
                parsed["target_ref_d"] = target_ref
                rows.append(parsed)
                print(f"Target Ref {target_ref} D -> Avg IOL {parsed.get('average_iol_d', 'N/A')} D")
                time.sleep(0.2)

        finally:
            browser.close()

    # Build CSV with all keys from first row (and ensure order)
    if not rows:
        print("No results collected.")
        return

    fieldnames = ["target_ref_d", "average_iol_d", "min_iol_d", "max_iol_d"]
    extra = [k for k in rows[0] if k not in fieldnames]
    fieldnames += extra

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"Saved {len(rows)} rows to {output_path}")
    return output_path


if __name__ == "__main__":
    run_batch()
