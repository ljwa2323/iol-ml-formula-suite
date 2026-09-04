"""
Fill Hill-RBF Calculator (https://rbfcalculator.com/online/index.html) with
patient, surgeon, biometry, and IOL data. Uses Playwright for browser automation.

Requirements:
  pip install playwright pandas openpyxl
  playwright install chromium

Optional (for auto-solving reCAPTCHA):
  pip install 2captcha-python
  set CAPTCHA_API_KEY or TWOCAPTCHA_API_KEY (or 2captcha API key in env)
  Then the script will use 2Captcha to solve reCAPTCHA (paid, ~$2-3/1000).

Usage:
  python fill_rbf_calculator.py           # use built-in config (USE_XLSX_TEST=False)
  python fill_rbf_calculator.py           # or first 3 rows from Excel (USE_XLSX_TEST=True)

Note: After "Click to calculate", a reCAPTCHA verification appears. If
      CAPTCHA_API_KEY is set and 2captcha-python is installed, it will be
      solved automatically; otherwise complete it manually. The script waits
      for you to press Enter before continuing or closing.
"""

import os
import re
import pandas as pd
from playwright.sync_api import sync_playwright

MEASURING_DEVICE = "HAAG-STREIT LENSTAR LS 900"
DEFAULT_N = "1.3375"
K1_AXIS_DEFAULT, K2_AXIS_DEFAULT = "90", "180"


def model_to_manufacturer(model):
    """Map IOL model string to Manufacturer for RBF. model: 晶体型号."""
    if not model or (isinstance(model, float) and pd.isna(model)):
        return "Alcon"
    s = str(model).strip().upper()
    if s.startswith("SN") or s.startswith("DCB") or s.startswith("ZCB") or s.startswith("TFNT") or s.startswith("ICB"):
        return "Alcon"
    if s.startswith("709") or s.startswith("409") or s.startswith("ZXR") or s.startswith("ZFR") or s.startswith("DFT"):
        return "Johnson & Johnson"
    if "A1UL" in s or s.startswith("A1UL"):
        return "Bausch"
    return "Alcon"

# --- Test mode: use first 3 rows from Excel ---
USE_XLSX_TEST = True
XLSX_PATH = "杨宁整合四文件合并_填补后.xlsx"
XLSX_N_ROWS = 3

# --- Config: edit these for your use (used when USE_XLSX_TEST=False) ---

PATIENT = {
    "id_email": "patient.demo@example.com",
    "name": "Smith",
    "first_name": "John",
    "dob": "15.06.1980",  # DD.MM.YYYY
    "gender": "Male",  # Female | Male | Not provided
}

# Fixed fake Surgeon (same for all runs; used by both run() and run_xlsx_test)
SURGEON = {
    "name": "Demo",
    "first_name": "Doctor",
    "email": "surgeon@demo.local",
}

# od (right eye) biometry
OD = {
    "target_refr": "0.00",
    "al": "23.45",      # mm
    "cct": "550",       # um
    "acd": "3.05",      # mm
    "lt": "4.52",       # mm
    "k1": "43.25",
    "k1_axis": "90",
    "k2": "44.50",
    "k2_axis": "180",
    "n": "1.3375",      # refractive index
    "wtw": "12.0",      # mm
}

# os (left eye) biometry
OS = {
    "target_refr": "0.00",
    "al": "23.38",
    "cct": "548",
    "acd": "3.02",
    "lt": "4.48",
    "k1": "43.50",
    "k1_axis": "85",
    "k2": "44.75",
    "k2_axis": "175",
    "n": "1.3375",
    "wtw": "11.9",
}

# IOL (both eyes)
IOL = {
    "manufacturer": "Alcon",
    "model": "SN60WF",
    "a_constant": "118.94",
}

# Set to True to click "Click to calculate" (you must complete reCAPTCHA manually)
CLICK_CALCULATE = True

# Optional: 2Captcha API key for auto-solving reCAPTCHA. Or set env CAPTCHA_API_KEY / TWOCAPTCHA_API_KEY.
CAPTCHA_API_KEY = ""

# Set to True to run browser in background (no window)
HEADLESS = False


def load_and_validate_rows(path, n):
    """
    Load first n rows from Excel, validate and clean. Return list of
    {patient, eye_side, eye_data, iol}. Skip rows with LT<1 or missing required.
    """
    df = pd.read_excel(path, sheet_name=0)
    out = []
    for i in range(min(n, len(df))):
        r = df.iloc[i]
        cct = r.get("CCT", r.get("cct"))
        if pd.isna(cct):
            print(f"  [skip row {i+1}] CCT missing")
            continue
        cct = float(cct)
        if cct < 1:
            cct = cct * 1000
        lt = r.get("LT", r.get("lt"))
        if pd.isna(lt):
            print(f"  [skip row {i+1}] LT missing")
            continue
        lt = float(lt)
        if lt < 1:
            print(f"  [skip row {i+1}] LT<1 (={lt}), skip")
            continue
        al = r.get("AL", r.get("al"))
        acd = r.get("ACD", r.get("acd"))
        k1 = r.get("K1", r.get("k1"))
        k2 = r.get("K2", r.get("k2"))
        w2w = r.get("W2W", r.get("wtw"))
        a_const = r.get("A_Constant", r.get("a_constant"))
        model = r.get("晶体型号", r.get("model"))
        if pd.isna(al) or pd.isna(k1) or pd.isna(k2) or pd.isna(a_const):
            print(f"  [skip row {i+1}] AL/K1/K2/A_Constant missing")
            continue
        if pd.isna(model) or str(model).strip() == "":
            model = "SN60WF"
        target = r.get("预留", r.get("target", 0.0))
        if pd.isna(target):
            target = 0.0
        target = float(target)
        # RBF requires Target Refr. in [-2.50, 1.00]; clamp and warn
        if target < -2.5:
            print(f"  [row {i+1}] Target Refr. {target} clamped to -2.50")
            target = -2.5
        elif target > 1.0:
            print(f"  [row {i+1}] Target Refr. {target} clamped to 1.00")
            target = 1.0
        eye = str(r.get("眼别", "OD")).strip().upper()
        if eye not in ("OD", "OS"):
            print(f"  [skip row {i+1}] eye not OD/OS: {eye}")
            continue
        if pd.isna(w2w):
            w2w = 12.0
        if pd.isna(acd):
            print(f"  [skip row {i+1}] ACD missing")
            continue
        pid = r.get("ID", "unknown")
        if pd.isna(pid):
            pid = "unknown"
        pid = str(pid).strip()
        age = r.get("Age", 60)
        if pd.isna(age):
            age = 60
        yob = int(2024 - float(age))
        dob = f"01.01.{yob}"
        g = r.get("Gender", "Not provided")
        if pd.isna(g) or str(g).strip() == "":
            g = "Not provided"
        else:
            g = "Female" if str(g).strip().lower().startswith("f") else "Male"
        patient = {"id_email": f"{pid}@local", "name": pid[:20] if len(pid) > 20 else pid, "first_name": "P", "dob": dob, "gender": g}
        eye_data = {
            "target_refr": f"{target:.2f}", "al": f"{float(al):.2f}", "cct": str(int(round(cct))),
            "acd": f"{float(acd):.2f}", "lt": f"{float(lt):.2f}", "k1": f"{float(k1):.2f}",
            "k1_axis": K1_AXIS_DEFAULT, "k2": f"{float(k2):.2f}", "k2_axis": K2_AXIS_DEFAULT,
            "n": DEFAULT_N, "wtw": f"{float(w2w):.1f}",
        }
        iol = {"manufacturer": model_to_manufacturer(model), "model": str(model).strip(), "a_constant": f"{float(a_const):.2f}"}
        out.append({"patient": patient, "eye_side": eye.lower(), "eye_data": eye_data, "iol": iol, "row_index": i + 1})
    return out


def get_frame(page):
    """Wait for and return the main calculator iframe."""
    page.wait_for_selector("iframe", timeout=15000)
    return page.frame_locator("iframe").first


def _solve_recaptcha(page, iframe_selector="iframe", api_key=None):
    """
    Solve reCAPTCHA v2/v3 via 2Captcha and inject the token.
    Returns True if solved and injected, False otherwise.
    Needs: pip install 2captcha-python, CAPTCHA_API_KEY or TWOCAPTCHA_API_KEY in env.
    """
    try:
        from twocaptcha import TwoCaptcha
    except ImportError:
        return False
    api_key = api_key or CAPTCHA_API_KEY or os.environ.get("CAPTCHA_API_KEY") or os.environ.get("TWOCAPTCHA_API_KEY")
    if not api_key:
        return False
    iframe = page.query_selector(iframe_selector)
    doc = None
    for ctx in [iframe.content_frame() if iframe else None, page]:
        if ctx is None:
            continue
        try:
            ctx.locator("[data-sitekey]").first.wait_for(state="attached", timeout=12000)
            doc = ctx
            break
        except Exception:
            continue
    if doc is None:
        return False
    sitekey = doc.locator("[data-sitekey]").first.get_attribute("data-sitekey")
    if not sitekey:
        return False
    action = None
    if doc.locator("[data-action]").count() > 0:
        action = doc.locator("[data-action]").first.get_attribute("data-action")
    url = page.url
    print("  Solving reCAPTCHA via 2Captcha (may take 10-30s)...")
    try:
        solver = TwoCaptcha(api_key)
        if action:
            result = solver.recaptcha(sitekey=sitekey, url=url, version="v3", action=action or "submit")
        else:
            result = solver.recaptcha(sitekey=sitekey, url=url)
        token = result.get("code", result) if isinstance(result, dict) else result
    except Exception as e:
        print(f"  2Captcha solve error: {e}")
        return False
    if not token:
        return False
    callback = None
    if doc.locator("[data-callback]").count() > 0:
        callback = doc.locator("[data-callback]").first.get_attribute("data-callback")
    js = """([t, cb]) => {
        var ta = document.getElementById('g-recaptcha-response') || document.querySelector('textarea[name="g-recaptcha-response"]') || document.querySelector('input[name="g-recaptcha-response"]');
        if (ta) { ta.value = t; if (ta.tagName === 'TEXTAREA') ta.innerHTML = t; }
        if (cb && typeof window[cb] === 'function') { window[cb](t); }
    }"""
    try:
        doc.evaluate(js, [token, callback])
        return True
    except Exception as e:
        print(f"  reCAPTCHA token inject error: {e}")
        return False


def _eye_loc(loc, side):
    return loc.first if side == "od" else loc.nth(1)


def _fill_dob(frame, value):
    """Fill Date of birth. Try label, placeholder, role+name."""
    for loc in [
        frame.get_by_label("Date of birth DD.MM.YYYY"),
        frame.get_by_label("Date of birth"),
        frame.get_by_placeholder("DD.MM.YYYY"),
        frame.get_by_role("textbox", name=re.compile(r"Date of birth", re.I)),
    ]:
        try:
            loc.first.fill(value, timeout=8000)
            return
        except Exception:
            continue
    raise RuntimeError("Could not find Date of birth field. Page layout may have changed.")


def fill_one_eye(frame, page, eye_side, eye_data, iol):
    """Fill only the od or os block (device, biometry, IOL)."""
    devs = frame.get_by_role("combobox").filter(has_text="Please select")
    _eye_loc(devs, eye_side).select_option(label=MEASURING_DEVICE)
    # fill() waits for element to be visible and enabled (event-driven)
    _eye_loc(frame.get_by_label("Target Refr.[D]"), eye_side).fill(eye_data["target_refr"])
    # Use role+name for AL: get_by_label("AL") can match Calculation ID and hit disabled calculation_id
    _eye_loc(frame.get_by_role("textbox", name=re.compile(r"^AL\b")), eye_side).fill(eye_data["al"])
    _eye_loc(frame.get_by_label("CCT"), eye_side).fill(eye_data["cct"])
    _eye_loc(frame.get_by_label("ACD"), eye_side).fill(eye_data["acd"])
    _eye_loc(frame.get_by_label("LT"), eye_side).fill(eye_data["lt"])
    _eye_loc(frame.get_by_label("K1"), eye_side).fill(eye_data["k1"])
    _eye_loc(frame.get_by_label("K1"), eye_side).press("Tab")
    page.keyboard.type(eye_data["k1_axis"])
    _eye_loc(frame.get_by_label("K2"), eye_side).fill(eye_data["k2"])
    _eye_loc(frame.get_by_label("K2"), eye_side).press("Tab")
    page.keyboard.type(eye_data["k2_axis"])
    # "n" (refractive index): name="n" can match "Gender"/"Name"; use ^n\b and select by label
    _eye_loc(frame.get_by_role("combobox", name=re.compile(r"^n\b", re.I)), eye_side).select_option(label=eye_data["n"])
    # WTW, IOL: scroll into view (often below fold) then fill (scroll_into_view_if_needed returns None, do not chain)
    for label, val in [
        ("WTW", eye_data["wtw"]),
        ("Manufacturer", iol["manufacturer"]),
        ("Model", iol["model"]),
        (re.compile(r"A-[Cc]onstant", re.I), iol["a_constant"]),
    ]:
        loc = _eye_loc(frame.get_by_label(label), eye_side)
        loc.scroll_into_view_if_needed()
        loc.fill(val)


def run_xlsx_test():
    """Load first N rows from Excel, for each valid row: goto, agree, fill one eye, click calculate, wait for reCAPTCHA."""
    rows = load_and_validate_rows(XLSX_PATH, XLSX_N_ROWS)
    if not rows:
        print("No valid rows from Excel. Nothing to run.")
        return
    print(f"Running RBF for {len(rows)} row(s) from {XLSX_PATH} (first {XLSX_N_ROWS} rows, after validation).")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context()
        page = context.new_page()
        for i, row in enumerate(rows):
            pid = row["patient"]["id_email"]
            side = row["eye_side"].upper()
            print(f"\n--- Row {row['row_index']} ({pid} {side}) ---")
            page.goto("https://rbfcalculator.com/online/index.html", wait_until="load")
            frame = get_frame(page)
            # Wait for iframe content: I agree or form. I agree appears with terms.
            try:
                frame.get_by_role("button", name="I agree").wait_for(state="visible", timeout=10000)
                frame.get_by_role("button", name="I agree").click()
            except Exception:
                pass
            # Ensure form is visible (in case terms were on top)
            try:
                id_field = frame.get_by_label("ID E-Mail")
                id_field.wait_for(state="visible", timeout=20000)
            except Exception:
                id_field = frame.get_by_role("textbox", name="ID E-Mail")
                id_field.wait_for(state="visible", timeout=20000)
            id_field.scroll_into_view_if_needed()
            # Patient
            id_field.fill(row["patient"]["id_email"])
            frame.get_by_label("Name").first.fill(row["patient"]["name"])
            frame.get_by_label("First name").first.fill(row["patient"]["first_name"])
            _fill_dob(frame, row["patient"]["dob"])
            frame.get_by_role("combobox", name="Gender").select_option(label=row["patient"]["gender"])
            # Surgeon: scroll into view then fill (Name.nth(1), First name.nth(1), E-Mail.last to avoid "ID E-Mail")
            sn = frame.get_by_label("Name").nth(1)
            sn.scroll_into_view_if_needed()
            sn.fill(SURGEON["name"])
            frame.get_by_label("First name").nth(1).fill(SURGEON["first_name"])
            frame.get_by_label("E-Mail").last.fill(SURGEON["email"])
            # One eye only
            fill_one_eye(frame, page, row["eye_side"], row["eye_data"], row["iol"])
            # "Click to calculate" can be a hidden <div> in DOM; scroll then force click
            btn = _eye_loc(frame.get_by_text("Click to calculate"), row["eye_side"])
            btn.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
            btn.click(force=True)
            if _solve_recaptcha(page, "iframe"):
                print("  reCAPTCHA solved.")
            else:
                print("  Tip: set CAPTCHA_API_KEY and install 2captcha-python to auto-solve.")
            print("Complete reCAPTCHA in the browser (if needed), then press Enter to continue to next row (or finish)...")
            input()
        browser.close()
    print("Done.")


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://rbfcalculator.com/online/index.html", wait_until="domcontentloaded")
        frame = get_frame(page)

        # 1. Accept terms (click waits for visible/enabled)
        frame.get_by_role("button", name="I agree").wait_for(state="visible", timeout=10000)
        frame.get_by_role("button", name="I agree").click()

        # 2. Patient
        frame.get_by_label("ID E-Mail").fill(PATIENT["id_email"])
        frame.get_by_label("Name").first.fill(PATIENT["name"])
        frame.get_by_label("First name").first.fill(PATIENT["first_name"])
        _fill_dob(frame, PATIENT["dob"])
        frame.get_by_role("combobox", name="Gender").select_option(label=PATIENT["gender"])

        # 3. Surgeon: scroll into view then fill (fake data; E-Mail.last to avoid "ID E-Mail")
        sn = frame.get_by_label("Name").nth(1)
        sn.scroll_into_view_if_needed()
        sn.fill(SURGEON["name"])
        frame.get_by_label("First name").nth(1).fill(SURGEON["first_name"])
        frame.get_by_label("E-Mail").last.fill(SURGEON["email"])

        # 4. Measuring device (od and os)
        devices = frame.get_by_role("combobox").filter(has_text="Please select")
        devices.first.select_option(label=MEASURING_DEVICE)
        devices.nth(1).select_option(label=MEASURING_DEVICE)

        # 5. od biometry (AL: use get_by_role to avoid matching disabled calculation_id)
        frame.get_by_label("Target Refr.[D]").first.fill(OD["target_refr"])
        frame.get_by_role("textbox", name=re.compile(r"^AL\b")).first.fill(OD["al"])
        frame.get_by_label("CCT").first.fill(OD["cct"])
        frame.get_by_label("ACD").first.fill(OD["acd"])
        frame.get_by_label("LT").first.fill(OD["lt"])
        frame.get_by_label("K1").first.fill(OD["k1"])
        frame.get_by_label("K1").first.press("Tab")
        page.keyboard.type(OD["k1_axis"])
        frame.get_by_label("K2").first.fill(OD["k2"])
        frame.get_by_label("K2").first.press("Tab")
        page.keyboard.type(OD["k2_axis"])
        frame.get_by_role("combobox", name=re.compile(r"^n\b", re.I)).first.select_option(label=OD["n"])
        w = frame.get_by_label("WTW").first
        w.scroll_into_view_if_needed()
        w.fill(OD["wtw"])
        # 6. od IOL (scroll into view, often below fold; scroll returns None, do not chain)
        m = frame.get_by_label("Manufacturer").first
        m.scroll_into_view_if_needed()
        m.fill(IOL["manufacturer"])
        x = frame.get_by_label("Model").first
        x.scroll_into_view_if_needed()
        x.fill(IOL["model"])
        a = frame.get_by_label(re.compile(r"A-[Cc]onstant", re.I)).first
        a.scroll_into_view_if_needed()
        a.fill(IOL["a_constant"])

        # 7. os biometry (AL: use get_by_role to avoid matching disabled calculation_id)
        frame.get_by_label("Target Refr.[D]").nth(1).fill(OS["target_refr"])
        frame.get_by_role("textbox", name=re.compile(r"^AL\b")).nth(1).fill(OS["al"])
        frame.get_by_label("CCT").nth(1).fill(OS["cct"])
        frame.get_by_label("ACD").nth(1).fill(OS["acd"])
        frame.get_by_label("LT").nth(1).fill(OS["lt"])
        frame.get_by_label("K1").nth(1).fill(OS["k1"])
        frame.get_by_label("K1").nth(1).press("Tab")
        page.keyboard.type(OS["k1_axis"])
        frame.get_by_label("K2").nth(1).fill(OS["k2"])
        frame.get_by_label("K2").nth(1).press("Tab")
        page.keyboard.type(OS["k2_axis"])
        frame.get_by_role("combobox", name=re.compile(r"^n\b", re.I)).nth(1).select_option(label=OS["n"])
        w = frame.get_by_label("WTW").nth(1)
        w.scroll_into_view_if_needed()
        w.fill(OS["wtw"])
        # 8. os IOL (scroll into view, often below fold; scroll returns None, do not chain)
        m = frame.get_by_label("Manufacturer").nth(1)
        m.scroll_into_view_if_needed()
        m.fill(IOL["manufacturer"])
        x = frame.get_by_label("Model").nth(1)
        x.scroll_into_view_if_needed()
        x.fill(IOL["model"])
        a = frame.get_by_label(re.compile(r"A-[Cc]onstant", re.I)).nth(1)
        a.scroll_into_view_if_needed()
        a.fill(IOL["a_constant"])

        if CLICK_CALCULATE:
            # "Click to calculate" can be a hidden <div> in DOM; scroll then force click
            btn = frame.get_by_text("Click to calculate").first
            btn.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
            btn.click(force=True)
            if _solve_recaptcha(page, "iframe"):
                print("  reCAPTCHA solved.")
            else:
                print("  Tip: set CAPTCHA_API_KEY and install 2captcha-python to auto-solve.")
            print("Verification (reCAPTCHA) dialog should appear. Complete it in the browser if needed.")
            input("Press Enter after completing reCAPTCHA to close the browser...")
        else:
            print("Form filled. Click 'Click to calculate' manually, then complete reCAPTCHA.")
            input("Press Enter to close the browser...")

        browser.close()


if __name__ == "__main__":
    if USE_XLSX_TEST:
        run_xlsx_test()
    else:
        run()
