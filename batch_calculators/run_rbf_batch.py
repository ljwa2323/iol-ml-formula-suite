"""
Fully automated Hill-RBF batch runner (Scheme A pipeline).

Reads:  data/rbf_pending.json  (from export_rbf_pending.py)
Writes: data/rbf_results.json  (+ optional Excel)
        Incremental save after each sample so crashes are resumable.

Flow per sample:
  open page -> I agree -> fill patient/surgeon/eye -> Click to calculate
  -> solve reCAPTCHA (2Captcha if API key set, else wait for manual solve)
  -> scrape Recommended IOL / table -> append results -> next

Requirements:
  pip install playwright pandas openpyxl
  playwright install chromium
  Optional full unattended: pip install 2captcha-python
    set CAPTCHA_API_KEY or TWOCAPTCHA_API_KEY

Usage (from batch_calculators or repo root):
  python run_rbf_batch.py
  python run_rbf_batch.py --pending ../data/rbf_pending.json --out ../data/rbf_results.json
  python run_rbf_batch.py --start 0 --limit 10 --delay 2
  python run_rbf_batch.py --excel ../data/HillRBF_results.xlsx
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
DEFAULT_PENDING = DATA / "rbf_pending.json"
DEFAULT_RESULTS = DATA / "rbf_results.json"
DEFAULT_EXCEL = DATA / "HillRBF_results.xlsx"

RBF_URL = "https://rbfcalculator.com/online/index.html"
MEASURING_DEVICE = "HAAG-STREIT LENSTAR LS 900"

SURGEON = {
    "name": "Demo",
    "first_name": "Doctor",
    "email": "surgeon@demo.local",
}

# Seconds to wait for result after Calculate (includes captcha solve time)
RESULT_WAIT_SEC = 180
# Poll interval while waiting for result / captcha
POLL_SEC = 2.0
HEADLESS = False


def _eye_loc(loc, side):
    return loc.first if side == "od" else loc.nth(1)


def load_json_list(path: Path):
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path} must be a JSON array")
    return data


def save_json_list(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def done_keys(results):
    keys = set()
    for row in results:
        kid = row.get("id") or row.get("ID")
        eye = row.get("eye") or row.get("眼别", "OD")
        if kid is not None and eye is not None:
            keys.add((str(kid).strip(), str(eye).strip().upper()))
    return keys


def get_frame(page):
    page.wait_for_selector("iframe", timeout=20000)
    return page.frame_locator("iframe").first


def _fill_dob(frame, value):
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
    raise RuntimeError("Could not find Date of birth field.")


def fill_one_eye(frame, page, eye_side, eye_data, iol):
    side = (eye_side or "od").lower()
    devs = frame.get_by_role("combobox").filter(has_text="Please select")
    _eye_loc(devs, side).select_option(label=MEASURING_DEVICE)
    _eye_loc(frame.get_by_label("Target Refr.[D]"), side).fill(eye_data["target_refr"])
    _eye_loc(frame.get_by_role("textbox", name=re.compile(r"^AL\b")), side).fill(eye_data["al"])
    _eye_loc(frame.get_by_label("CCT"), side).fill(eye_data["cct"])
    _eye_loc(frame.get_by_label("ACD"), side).fill(eye_data["acd"])
    _eye_loc(frame.get_by_label("LT"), side).fill(eye_data["lt"])
    _eye_loc(frame.get_by_label("K1"), side).fill(eye_data["k1"])
    _eye_loc(frame.get_by_label("K1"), side).press("Tab")
    page.keyboard.type(eye_data.get("k1_axis", "90"))
    _eye_loc(frame.get_by_label("K2"), side).fill(eye_data["k2"])
    _eye_loc(frame.get_by_label("K2"), side).press("Tab")
    page.keyboard.type(eye_data.get("k2_axis", "180"))
    _eye_loc(frame.get_by_role("combobox", name=re.compile(r"^n\b", re.I)), side).select_option(
        label=eye_data.get("n", "1.3375")
    )
    for label, val in [
        ("WTW", eye_data["wtw"]),
        ("Manufacturer", iol["manufacturer"]),
        ("Model", iol["model"]),
        (re.compile(r"A-[Cc]onstant", re.I), iol["a_constant"]),
    ]:
        loc = _eye_loc(frame.get_by_label(label), side)
        loc.scroll_into_view_if_needed()
        loc.fill(val)


def solve_recaptcha(page, api_key=None):
    """Solve reCAPTCHA via 2Captcha and inject token. Returns True on success."""
    try:
        from twocaptcha import TwoCaptcha
    except ImportError:
        return False
    api_key = (
        api_key
        or os.environ.get("CAPTCHA_API_KEY")
        or os.environ.get("TWOCAPTCHA_API_KEY")
        or ""
    )
    if not api_key:
        return False

    doc = None
    iframe_el = page.query_selector("iframe")
    for ctx in [iframe_el.content_frame() if iframe_el else None, page]:
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
    print("  Solving reCAPTCHA via 2Captcha...")
    try:
        solver = TwoCaptcha(api_key)
        if action:
            result = solver.recaptcha(sitekey=sitekey, url=page.url, version="v3", action=action)
        else:
            result = solver.recaptcha(sitekey=sitekey, url=page.url)
        token = result.get("code", result) if isinstance(result, dict) else result
    except Exception as e:
        print(f"  2Captcha error: {e}")
        return False
    if not token:
        return False
    callback = None
    if doc.locator("[data-callback]").count() > 0:
        callback = doc.locator("[data-callback]").first.get_attribute("data-callback")
    js = """([t, cb]) => {
        var ta = document.getElementById('g-recaptcha-response')
            || document.querySelector('textarea[name="g-recaptcha-response"]')
            || document.querySelector('input[name="g-recaptcha-response"]');
        if (ta) { ta.value = t; if (ta.tagName === 'TEXTAREA') ta.innerHTML = t; }
        if (cb && typeof window[cb] === 'function') { window[cb](t); }
    }"""
    try:
        doc.evaluate(js, [token, callback])
        return True
    except Exception as e:
        print(f"  Token inject error: {e}")
        return False


def collect_from_frame(frame, page):
    """Scrape Recommended IOL and table text from calculator iframe."""
    result = {
        "recommended_iol": None,
        "result_text": "",
        "table_text": "",
        "in_bounds": None,
        "complete": False,
        "reason": None,
    }
    try:
        text = frame.locator("body").inner_text(timeout=5000)
    except Exception:
        try:
            text = page.inner_text("body")
        except Exception:
            text = ""

    m = re.search(r"Recommended\s*IOL[:\s]*([\d.\-]+)", text, re.I)
    if not m:
        m = re.search(r"IOL\s*Power\s*@\s*Emmetropia[^\d\-]*([\d.\-]+)", text, re.I)
    if not m:
        m = re.search(r"Emmetropia\s*[\[\(]?\s*D\s*[\]\)]?\s*[:\s]*([\d.\-]+)", text, re.I)
    if m:
        try:
            result["recommended_iol"] = float(m.group(1))
        except ValueError:
            pass

    if re.search(r"out[\s\-]?of[\s\-]?bounds", text, re.I):
        result["in_bounds"] = False
    elif re.search(r"in[\s\-]?bounds", text, re.I):
        result["in_bounds"] = True

    # Prefer structured JSON blobs if present
    try:
        raw_json = frame.evaluate(
            """() => {
            var els = document.querySelectorAll('pre, div');
            for (var i = 0; i < els.length; i++) {
                var raw = (els[i].textContent || '').trim();
                if (raw.length < 200 || raw.length > 8000) continue;
                if (raw.indexOf('calculationResult') === -1) continue;
                if (raw.indexOf('"od"') === -1 && raw.indexOf('"os"') === -1) continue;
                return raw;
            }
            return null;
        }"""
        )
        if raw_json:
            data = json.loads(raw_json)
            for eye_key in ("od", "os"):
                cr = (data.get(eye_key) or {}).get("calculationResult")
                if not cr:
                    continue
                for k in ("iolPowerAtEmmetropia", "recommendedIol", "recommendedIOL", "emmetropiaIol"):
                    if cr.get(k) is not None and result["recommended_iol"] is None:
                        result["recommended_iol"] = float(cr[k])
                if not result["table_text"]:
                    for tk in ("resultTable", "iolRefrTable"):
                        if cr.get(tk) is not None:
                            result["table_text"] = (
                                cr[tk] if isinstance(cr[tk], str) else json.dumps(cr[tk])
                            )
                            break
    except Exception:
        pass

    if not result["table_text"]:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        keep = []
        capture = False
        for ln in lines:
            if re.search(r"IOL\s*Power|IOL\[D\]|Constants:\s*A=", ln, re.I):
                capture = True
            if capture:
                keep.append(ln)
                if len(keep) > 40:
                    break
        if keep:
            result["table_text"] = "\n".join(keep)

    if result["recommended_iol"] is not None or result["table_text"]:
        result["complete"] = True
        if result["recommended_iol"] is not None:
            result["result_text"] = f"Recommended IOL: {result['recommended_iol']}"
    else:
        result["reason"] = "No Recommended IOL or result table yet"
    return result


def wait_for_result(frame, page, api_key, wait_sec=RESULT_WAIT_SEC):
    """After Calculate: try 2Captcha once, then poll until result or timeout."""
    solved = solve_recaptcha(page, api_key=api_key)
    if solved:
        print("  reCAPTCHA solved.")
        time.sleep(1.5)
    else:
        print("  Waiting for reCAPTCHA + result (solve captcha in browser if shown)...")

    deadline = time.time() + wait_sec
    last_reason = None
    while time.time() < deadline:
        scraped = collect_from_frame(frame, page)
        if scraped["complete"]:
            return scraped
        last_reason = scraped.get("reason")
        time.sleep(POLL_SEC)
    scraped = collect_from_frame(frame, page)
    if not scraped["complete"]:
        scraped["reason"] = last_reason or "Timeout waiting for result"
    return scraped


def fill_and_calculate(page, payload):
    patient = payload.get("patient") or {}
    eye_side = (payload.get("eye_side") or (payload.get("eye") or "od").lower()).lower()
    eye_data = payload.get("eye_data") or {}
    iol = payload.get("iol") or {}

    page.goto(RBF_URL, wait_until="load", timeout=60000)
    frame = get_frame(page)
    try:
        frame.get_by_role("button", name="I agree").wait_for(state="visible", timeout=10000)
        frame.get_by_role("button", name="I agree").click()
    except Exception:
        pass

    id_field = frame.get_by_label("ID E-Mail")
    try:
        id_field.wait_for(state="visible", timeout=20000)
    except Exception:
        id_field = frame.get_by_role("textbox", name="ID E-Mail")
        id_field.wait_for(state="visible", timeout=20000)
    id_field.scroll_into_view_if_needed()
    id_field.fill(patient.get("id_email") or f"{payload.get('id', 'unknown')}@local")
    frame.get_by_label("Name").first.fill(patient.get("name") or str(payload.get("id", "P"))[:20])
    frame.get_by_label("First name").first.fill(patient.get("first_name") or "P")
    _fill_dob(frame, patient.get("dob") or "01.01.1960")
    gender = patient.get("gender") or "Not provided"
    frame.get_by_role("combobox", name="Gender").select_option(label=gender)

    sn = frame.get_by_label("Name").nth(1)
    sn.scroll_into_view_if_needed()
    sn.fill(SURGEON["name"])
    frame.get_by_label("First name").nth(1).fill(SURGEON["first_name"])
    frame.get_by_label("E-Mail").last.fill(SURGEON["email"])

    fill_one_eye(frame, page, eye_side, eye_data, iol)

    btn = _eye_loc(frame.get_by_text("Click to calculate"), eye_side)
    btn.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
    btn.click(force=True)
    return frame


def results_to_excel(results, excel_path: Path):
    rows = []
    for r in results:
        rows.append(
            {
                "Row_Index": r.get("row_index"),
                "ID": r.get("id"),
                "Eye": r.get("eye"),
                "HillRBF_Recommended_IOL": r.get("recommended_iol"),
                "HillRBF_InBounds": r.get("in_bounds"),
                "HillRBF_ResultText": r.get("result_text"),
                "HillRBF_Table": r.get("table_text"),
                "Success": bool(r.get("recommended_iol") is not None or r.get("table_text")),
                "Error": r.get("error") or r.get("reason"),
            }
        )
    pd.DataFrame(rows).to_excel(excel_path, index=False)


def run_batch(
    pending_path: Path,
    results_path: Path,
    excel_path: Path | None,
    start: int,
    limit: int | None,
    delay: float,
    api_key: str | None,
    wait_sec: int,
    headless: bool,
):
    pending = load_json_list(pending_path)
    if not pending:
        print(f"No pending samples in {pending_path}")
        print("Run: python export_rbf_pending.py")
        return

    results = load_json_list(results_path)
    done = done_keys(results)
    todo = []
    for item in pending:
        kid = str(item.get("id", "")).strip()
        eye = str(item.get("eye") or item.get("eye_side") or "OD").strip().upper()
        if (kid, eye) in done:
            continue
        todo.append(item)

    if start:
        todo = todo[start:]
    if limit is not None and limit > 0:
        todo = todo[:limit]

    print(f"Pending file: {len(pending)} | already done: {len(done)} | to run: {len(todo)}")
    if not todo:
        print("Nothing to run.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(30000)

        for i, payload in enumerate(todo):
            pid = payload.get("id")
            eye = str(payload.get("eye") or payload.get("eye_side") or "OD").upper()
            print(f"\n--- [{i + 1}/{len(todo)}] {pid} {eye} ---")
            row_out = {
                "id": pid,
                "eye": eye,
                "row_index": payload.get("row_index"),
                "recommended_iol": None,
                "result_text": None,
                "table_text": None,
                "in_bounds": None,
                "error": None,
            }
            try:
                frame = fill_and_calculate(page, payload)
                scraped = wait_for_result(frame, page, api_key=api_key, wait_sec=wait_sec)
                if scraped.get("complete"):
                    row_out["recommended_iol"] = scraped.get("recommended_iol")
                    row_out["result_text"] = scraped.get("result_text")
                    row_out["table_text"] = scraped.get("table_text")
                    row_out["in_bounds"] = scraped.get("in_bounds")
                    print(f"  OK Recommended IOL={row_out['recommended_iol']}")
                else:
                    row_out["error"] = scraped.get("reason") or "incomplete"
                    print(f"  FAIL: {row_out['error']}")
            except Exception as e:
                row_out["error"] = str(e)
                print(f"  ERROR: {e}")

            results.append(row_out)
            save_json_list(results_path, results)
            if excel_path:
                results_to_excel(results, excel_path)
            if delay > 0 and i < len(todo) - 1:
                time.sleep(delay)

        browser.close()

    ok = sum(1 for r in results if r.get("recommended_iol") is not None)
    print(f"\nDone. Results: {results_path} ({len(results)} rows, {ok} with IOL)")
    if excel_path:
        print(f"Excel: {excel_path}")


def main():
    ap = argparse.ArgumentParser(description="Fully automated Hill-RBF batch (Scheme A)")
    ap.add_argument("--pending", type=str, default=str(DEFAULT_PENDING), help="rbf_pending.json path")
    ap.add_argument("--out", type=str, default=str(DEFAULT_RESULTS), help="rbf_results.json path")
    ap.add_argument("--excel", type=str, default=str(DEFAULT_EXCEL), help="Excel output path (empty to skip)")
    ap.add_argument("--start", type=int, default=0, help="Skip first N pending (after done-filter)")
    ap.add_argument("--limit", type=int, default=None, help="Max samples this run")
    ap.add_argument("--delay", type=float, default=2.0, help="Delay between samples (sec)")
    ap.add_argument("--wait", type=int, default=RESULT_WAIT_SEC, help="Max wait per sample for captcha+result")
    ap.add_argument("--headless", action="store_true", help="Run browser headless (needs 2Captcha)")
    ap.add_argument("--api-key", type=str, default=None, help="2Captcha API key (or env CAPTCHA_API_KEY)")
    args = ap.parse_args()

    excel = Path(args.excel) if args.excel else None
    run_batch(
        pending_path=Path(args.pending),
        results_path=Path(args.out),
        excel_path=excel,
        start=args.start,
        limit=args.limit,
        delay=args.delay,
        api_key=args.api_key,
        wait_sec=args.wait,
        headless=args.headless or HEADLESS,
    )


if __name__ == "__main__":
    main()
