"""
Fetch EVO IOL Calculator results via Playwright (browser automation).
Batch get IOL power predictions by filling the form and clicking Calculate.

Requirements:
  pip install playwright pandas openpyxl
  playwright install chromium

Usage:
  python evo_iol_fetch.py                    # run single example
  python evo_iol_fetch.py --batch data.csv   # batch from CSV
  python evo_iol_fetch.py --batch data.xlsx --out results.xlsx   # batch from Excel (e.g. Yang Ning file)

Excel columns (Yang Ning): AL, K1, K2, A_Constant, ACD, LT, CCT, 预留, 眼别, 晶体型号, ID
CSV columns: al, k1, k2, a_constant, target_ref, acd, lt, cct, iol_model, k_index, eye
"""

import argparse
import json
import os
import sys
from urllib.parse import urljoin

BASE_URL = "https://www.evoiolcalculator.com/"
CALC_URL = urljoin(BASE_URL, "calculator.aspx")

# Short timeout so stuck samples are skipped quickly (ms)
ACTION_TIMEOUT_MS = 10000

# IOL model dropdown values (same order as on site)
IOL_MODELS = [
    "Standard", "Tecnis", "AR40e/E/M", "MA60MA", "Alcon SA60AT", "Alcon SA60WF",
    "Alcon SN60WF", "Alcon CNA0T0", "Alcon Vivity", "Alcon Panoptix", "Alcon MTA4U0",
    "B&L MX60E", "B&L Aspire", "B&L Beyond", "B&L Envy", "B&L LuxGood", "B&L LuxSmart", "B&L LuxLife",
    "J&J ZCB00", "J&J Eyhance", "J&J PureSee", "J&J Synergy",
    "Kowa PU6A/AS", "Kowa PN6A/AS", "Rayner EMV", "Rayner Galaxy",
    "Zeiss 409M/MP", "Zeiss 509M/MP", "Zeiss 621P/PY", "Zeiss 829MP", "Zeiss 839MP", "Zeiss 841P",
]


def model_to_evo_iol(model_str):
    """Map short IOL model (e.g. SN60WF, ZCB00) to EVO dropdown value."""
    try:
        if model_str is None or (isinstance(model_str, float) and model_str != model_str):
            return "Standard"
    except Exception:
        return "Standard"
    s = str(model_str).strip().upper()
    for evo in IOL_MODELS:
        if s in evo.upper().replace(" ", "").replace("&", ""):
            return evo
    if "SN60" in s or "SA60" in s or "CNA0" in s or "VIVITY" in s or "PANOPTIX" in s or "MTA4" in s:
        for evo in IOL_MODELS:
            if evo.startswith("Alcon ") and s[:4] in evo:
                return evo
    if "ZCB" in s or "EYHANCE" in s or "PURESEE" in s or "SYNERGY" in s:
        for evo in IOL_MODELS:
            if evo.startswith("J&J"):
                if "ZCB" in s and "ZCB00" in evo:
                    return evo
                if "EYHANCE" in s or "EYHANCE" in evo.upper():
                    return evo
                if "SYNERGY" in s or "SYNERGY" in evo.upper():
                    return evo
        return "J&J ZCB00"
    return "Standard"


def _parse_result_from_page(page, timeout=ACTION_TIMEOUT_MS):
    """
    Parse IOL Power and Refraction (SE) from result panel on current page.
    Returns dict: { "iol_powers": [...], "refractions": [...], "params": {...} }
    """
    out = {"iol_powers": [], "refractions": [], "params": {}}
    for i in range(1, 6):
        iol_val = None
        ref_val = None
        try:
            loc_iol = page.locator('[id$="lblResult_IOL%d"]' % i).first
            if loc_iol.count() > 0:
                iol_val = float(loc_iol.text_content(timeout=timeout).strip())
        except Exception:
            pass
        try:
            loc_ref = page.locator('[id$="lblResult_Refraction%d"]' % i).first
            if loc_ref.count() > 0:
                ref_val = float(loc_ref.text_content(timeout=timeout).strip())
        except Exception:
            pass
        out["iol_powers"].append(iol_val)
        out["refractions"].append(ref_val)
    try:
        loc_p1 = page.locator("#Labelpara1").first
        if loc_p1.count() > 0:
            out["params"]["para1"] = loc_p1.text_content(timeout=timeout).strip()
    except Exception:
        pass
    try:
        loc_p2 = page.locator("#Labelpara2").first
        if loc_p2.count() > 0:
            out["params"]["para2"] = loc_p2.text_content(timeout=timeout).strip()
    except Exception:
        pass
    return out


def _fill_form(page, al, k1, k2, a_constant=118.5, target_refraction=0,
               acd="", lt="", cct="", iol_model="Standard", k_index="1.3375",
               right_eye=True, patient_name="", timeout=ACTION_TIMEOUT_MS, **_kwargs):
    """Fill calculator form fields. Patient Name is required by the site."""
    name = str(patient_name).strip() if patient_name else "Batch"
    page.locator("#TextBoxName").fill(name, timeout=timeout)
    page.locator("#txtAL").fill(str(al), timeout=timeout)
    page.locator("input[name='txtAConstant']").fill(str(a_constant), timeout=timeout)
    page.locator("input[name='txtK1']").fill(str(k1), timeout=timeout)
    page.locator("input[name='txtK2']").fill(str(k2), timeout=timeout)
    page.locator("#txtRefraction").fill(str(target_refraction), timeout=timeout)
    page.locator("#txtACD").fill(str(acd) if acd else "", timeout=timeout)
    page.locator("input[name='txtLT']").fill(str(lt) if lt else "", timeout=timeout)
    page.locator("input[name='txtCCT']").fill(str(cct) if cct else "", timeout=timeout)
    iol = iol_model if iol_model in IOL_MODELS else "Standard"
    page.locator("select[name='DropDownIOLModel']").select_option(label=iol, timeout=timeout)
    k = k_index if k_index in ("1.3375", "1.3315", "1.332") else "1.3375"
    page.locator("select[name='DropDownKIndex']").select_option(label=k, timeout=timeout)
    if right_eye:
        page.locator("input[value='1'][name='RadioButtonRLEye']").check(timeout=timeout)
    else:
        page.locator("input[value='0'][name='RadioButtonRLEye']").check(timeout=timeout)


def fetch_one(page, al, k1, k2, a_constant=118.5, target_refraction=0,
             acd="", lt="", cct="", iol_model="Standard", k_index="1.3375",
             right_eye=True, patient_name="", timeout=None, **kwargs):
    """
    Fill form with given biometry, click Calculate, parse result, then Back.
    Returns parsed result dict: { "iol_powers", "refractions", "params" }.
    Uses Playwright page (must be on calculator form or about to load CALC_URL).
    """
    if timeout is None:
        timeout = ACTION_TIMEOUT_MS
    try:
        current_url = page.url
        if "calculator.aspx" not in current_url:
            page.goto(CALC_URL, timeout=timeout)
        _fill_form(page, al=al, k1=k1, k2=k2, a_constant=a_constant,
                   target_refraction=target_refraction, acd=acd, lt=lt, cct=cct,
                   iol_model=iol_model, k_index=k_index, right_eye=right_eye,
                   patient_name=patient_name, timeout=timeout, **kwargs)
        page.locator('input[name="btnCalculate"]').first.click(timeout=timeout)
        # Trigger: wait for page change - result view has new element (Back button only on result page)
        page.wait_for_selector('input[name="btnBack"]', state="visible", timeout=timeout)
        # Trigger: wait for result table content ready (last cell has numeric value)
        page.wait_for_function(
            """() => {
                const el = document.querySelector('[id$="lblResult_IOL5"]');
                if (!el || !el.innerText) return false;
                const t = el.innerText.trim();
                return t !== '' && !isNaN(parseFloat(t));
            }""",
            timeout=timeout,
        )
        result = _parse_result_from_page(page, timeout=timeout)
        back_btn = page.locator('input[name="btnBack"]').first
        if back_btn.count() > 0:
            back_btn.click(timeout=timeout)
            page.wait_for_load_state("networkidle", timeout=timeout)
        return result
    except Exception as e:
        raise RuntimeError("EVO fetch failed: %s" % e) from e


def main():
    ap = argparse.ArgumentParser(description="EVO IOL Calculator batch fetch (Playwright)")
    ap.add_argument("--batch", metavar="CSV", help="Batch input CSV (columns: al, k1, k2, a_constant, target_ref, ...)")
    ap.add_argument("--al", default="23.5", help="Axial length (mm)")
    ap.add_argument("--k1", default="43.5", help="K1 (D)")
    ap.add_argument("--k2", default="44.0", help="K2 (D)")
    ap.add_argument("--a-constant", default="118.5", dest="a_constant")
    ap.add_argument("--target-ref", default="0", dest="target_refraction")
    ap.add_argument("--acd", default="", help="Optical ACD (optional)")
    ap.add_argument("--out", metavar="FILE", help="Output CSV path for batch results")
    ap.add_argument("--headed", action="store_true", help="Run browser with GUI (default: headless)")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        page = browser.new_page()
        page.goto(CALC_URL, timeout=30000)

        if args.batch:
            try:
                import pandas as pd
            except ImportError:
                print("Batch mode requires pandas. pip install pandas", file=sys.stderr)
                sys.exit(1)
            batch_path = args.batch
            if str(batch_path).lower().endswith(".xlsx"):
                df = pd.read_excel(batch_path, sheet_name=0)
            else:
                df = pd.read_csv(batch_path)
            # Normalize column names (allow al / axial_length / Yang Ning AL, etc.)
            col_map = {
                "axial_length": "al", "AL": "al", "AxialLength": "al",
                "K1": "k1", "k1_flat": "k1",
                "K2": "k2", "k2_steep": "k2",
                "a_constant": "a_constant", "AConstant": "a_constant", "A_Constant": "a_constant",
                "target_ref": "target_refraction", "target_refraction": "target_refraction", "Refraction": "target_refraction",
                "ACD": "acd", "acd": "acd",
                "LT": "lt", "lt": "lt",
                "CCT": "cct", "cct": "cct",
                "IOL_Model": "iol_model", "iol_model": "iol_model",
                "k_index": "k_index", "KIndex": "k_index",
                "eye": "eye",
            }
            for cn_en in (("预留", "target_refraction"), ("晶体型号", "iol_model"), ("眼别", "eye")):
                col_map[cn_en[0]] = cn_en[1]
            df = df.rename(columns={c: col_map.get(c, c) for c in df.columns})
            required = ["al", "k1", "k2"]
            for c in required:
                if c not in df.columns:
                    print("Missing column: %s" % c, file=sys.stderr)
                    sys.exit(1)

            n = len(df)
            print("Batch: %d rows from %s" % (n, batch_path), file=sys.stderr)

            progress_path = (str(args.out) + ".progress.jsonl") if args.out else os.path.join(os.path.dirname(os.path.abspath(batch_path)), "evo_iol_progress.jsonl")

            results = [None] * n
            if os.path.isfile(progress_path):
                with open(progress_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                            i = int(rec["i"])
                            if 0 <= i < n:
                                results[i] = rec["result"]
                        except Exception:
                            pass
                prev_ok = sum(1 for r in results if r is not None and r.get("error") is None)
                print("Resumed: %d rows from %s" % (prev_ok, progress_path), file=sys.stderr)

            page.set_default_timeout(ACTION_TIMEOUT_MS)
            progress_file = open(progress_path, "a", encoding="utf-8")
            try:
                for idx in range(n):
                    pct = 100.0 * (idx + 1) / n
                    print("[%d/%d] %.1f%%" % (idx + 1, n, pct), file=sys.stderr)
                    row = df.iloc[idx]
                    if results[idx] is not None:
                        continue
                    al = row.get("al")
                    k1 = row.get("k1")
                    k2 = row.get("k2")
                    if pd.isna(al) or pd.isna(k1) or pd.isna(k2):
                        results[idx] = {"_row": idx, "error": "missing AL/K1/K2"}
                        continue
                    kw = {"al": al, "k1": k1, "k2": k2, "timeout": ACTION_TIMEOUT_MS}
                    for k in ["a_constant", "target_refraction", "acd", "lt", "cct", "k_index"]:
                        if k in row and pd.notna(row.get(k)):
                            kw[k] = row.get(k)
                    if "a_constant" not in kw or pd.isna(kw.get("a_constant")):
                        kw["a_constant"] = 118.5
                    if "target_refraction" not in kw or pd.isna(kw.get("target_refraction")):
                        kw["target_refraction"] = 0
                    if "cct" in kw and kw["cct"] is not None:
                        try:
                            cct_val = float(kw["cct"])
                            if 0 < cct_val < 1:
                                kw["cct"] = str(int(round(cct_val * 1000)))
                            else:
                                kw["cct"] = str(int(round(cct_val)))
                        except (TypeError, ValueError):
                            pass
                    if "iol_model" in row and pd.notna(row.get("iol_model")):
                        kw["iol_model"] = model_to_evo_iol(row.get("iol_model"))
                    else:
                        kw["iol_model"] = "Standard"
                    eye_val = row.get("eye", "OD")
                    if pd.isna(eye_val):
                        eye_val = "OD"
                    eye_str = str(eye_val).strip().upper()
                    kw["right_eye"] = eye_str not in ("OS", "L", "LEFT", "0")
                    try:
                        res = fetch_one(page, **kw)
                        res["_row"] = idx
                        results[idx] = res
                        progress_file.write(json.dumps({"i": idx, "result": res}, ensure_ascii=False) + "\n")
                        progress_file.flush()
                    except Exception as e:
                        results[idx] = {"_row": idx, "error": str(e)}
            finally:
                progress_file.close()

            ok = sum(1 for r in results if r is not None and r.get("error") is None)
            err = n - ok
            print("Done. OK: %d, errors/skipped: %d" % (ok, err), file=sys.stderr)

            def _row_to_out(r, idx):
                if r is None:
                    r = {"_row": idx, "error": "skipped"}
                return {
                    "row": r.get("_row"),
                    "iol_1": r.get("iol_powers", [None] * 5)[0] if isinstance(r.get("iol_powers"), list) else None,
                    "iol_2": r.get("iol_powers", [None] * 5)[1] if isinstance(r.get("iol_powers"), list) else None,
                    "iol_3": r.get("iol_powers", [None] * 5)[2] if isinstance(r.get("iol_powers"), list) else None,
                    "iol_4": r.get("iol_powers", [None] * 5)[3] if isinstance(r.get("iol_powers"), list) else None,
                    "iol_5": r.get("iol_powers", [None] * 5)[4] if isinstance(r.get("iol_powers"), list) else None,
                    "ref_1": r.get("refractions", [None] * 5)[0] if isinstance(r.get("refractions"), list) else None,
                    "ref_2": r.get("refractions", [None] * 5)[1] if isinstance(r.get("refractions"), list) else None,
                    "ref_3": r.get("refractions", [None] * 5)[2] if isinstance(r.get("refractions"), list) else None,
                    "ref_4": r.get("refractions", [None] * 5)[3] if isinstance(r.get("refractions"), list) else None,
                    "ref_5": r.get("refractions", [None] * 5)[4] if isinstance(r.get("refractions"), list) else None,
                    "error": r.get("error"),
                }
            out_df = pd.DataFrame([_row_to_out(results[idx], idx) for idx in range(n)])
            if args.out:
                print("Writing output to %s ..." % args.out, file=sys.stderr)
                if str(args.out).lower().endswith(".xlsx"):
                    for c in ["EVO_iol_1", "EVO_iol_2", "EVO_iol_3", "EVO_iol_4", "EVO_iol_5", "EVO_ref_1", "EVO_ref_2", "EVO_ref_3", "EVO_ref_4", "EVO_ref_5", "EVO_error"]:
                        df[c] = None
                    for _, r in out_df.iterrows():
                        i = r["row"]
                        for suf in ["1", "2", "3", "4", "5"]:
                            df.loc[i, "EVO_iol_" + suf] = r.get("iol_" + suf)
                            df.loc[i, "EVO_ref_" + suf] = r.get("ref_" + suf)
                        df.loc[i, "EVO_error"] = r.get("error")
                    df.to_excel(args.out, index=False)
                else:
                    out_df.to_csv(args.out, index=False)
                print("Wrote %s" % args.out)
            else:
                print(out_df.to_string())
            return

        # Single run
        result = fetch_one(
            page,
            al=args.al,
            k1=args.k1,
            k2=args.k2,
            a_constant=args.a_constant,
            target_refraction=args.target_refraction,
            acd=args.acd or None,
        )
        print("Params:", result.get("params"))
        print("IOL (SE):", result.get("iol_powers"))
        print("Refraction (SE):", result.get("refractions"))

    # browser closed by context manager


if __name__ == "__main__":
    main()
