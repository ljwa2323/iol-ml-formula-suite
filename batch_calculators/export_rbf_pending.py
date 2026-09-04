"""
Export pending rows from fill Excel to JSON for the RBF browser extension / run_rbf_batch.py.
Reads: data/杨宁整合四文件合并_填补后.xlsx
Optional: data/rbf_results.json (list of {id, eye}) to exclude already-done.
Writes: data/rbf_pending.json (array of form payloads for extension).

Filter: only non-refractive-surgery (non-屈光术后史) patients.
Default sample: ~150 cases, evenly split high myopia / ordinary.
Use --all to export every eligible row (no sampling).

Usage:
  python export_rbf_pending.py
  python export_rbf_pending.py --all
  python export_rbf_pending.py --total 300
"""
import argparse
import json
import random
import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
FILL_XLSX = DATA / "杨宁整合四文件合并_填补后.xlsx"
RESULTS_JSON = DATA / "rbf_results.json"
OUT_JSON = DATA / "rbf_pending.json"

K1_AXIS_DEFAULT, K2_AXIS_DEFAULT = "90", "180"
DEFAULT_N = "1.3375"

# Filter and sampling
CAT_TYPE_COL = "白内障类型"  # cataract type column in Excel
POST_REFRACTIVE_VALUES = ("屈光术后",)  # exclude these (refractive surgery history)
HIGH_MYOPIA_AL_MM = 26.0  # axial length >= this treated as high myopia if type unclear
TARGET_TOTAL = 150  # total samples to export
RANDOM_SEED = 42  # for reproducible sampling


def model_to_manufacturer(model):
    if not model or (isinstance(model, float) and pd.isna(model)):
        return "Alcon"
    s = str(model).strip().upper()
    if s.startswith("SN") or s.startswith("DCB") or s.startswith("ZCB") or "TFNT" in s or s.startswith("ICB"):
        return "Alcon"
    if s.startswith("709") or s.startswith("409") or "ZXR" in s or "ZFR" in s or "DFT" in s:
        return "Johnson & Johnson"
    if "A1UL" in s:
        return "Bausch"
    return "Alcon"


def main():
    ap = argparse.ArgumentParser(description="Export RBF pending JSON")
    ap.add_argument("--all", action="store_true", help="Export all eligible rows (no sampling)")
    ap.add_argument("--total", type=int, default=TARGET_TOTAL, help="Sample size when not --all")
    ap.add_argument("--input", "-i", type=str, default=str(FILL_XLSX), help="Input Excel path")
    ap.add_argument("--out", "-o", type=str, default=str(OUT_JSON), help="Output pending JSON")
    args = ap.parse_args()
    fill_xlsx = Path(args.input)
    out_json = Path(args.out)
    target_total = args.total

    if not fill_xlsx.exists():
        print(f"Input not found: {fill_xlsx}")
        return
    done_keys = set()
    if RESULTS_JSON.exists():
        try:
            with open(RESULTS_JSON, "r", encoding="utf-8") as f:
                done_list = json.load(f)
            for row in done_list:
                kid = row.get("id") or row.get("ID")
                eye = row.get("eye") or row.get("眼别", "OD")
                if kid is not None and eye is not None:
                    done_keys.add((str(kid).strip(), str(eye).strip().upper()))
            print(f"Loaded {len(done_keys)} done (ID, eye) from {RESULTS_JSON}")
        except Exception as e:
            print(f"Could not load results: {e}")

    df = pd.read_excel(fill_xlsx, sheet_name=0)
    has_cat_type = CAT_TYPE_COL in df.columns
    if not has_cat_type:
        print(f"Warning: column '{CAT_TYPE_COL}' not found; cannot filter by refractive surgery history.")

    high_myopia_candidates = []
    ordinary_candidates = []

    for i in range(len(df)):
        r = df.iloc[i]
        # Exclude refractive surgery history (non-屈光术后史 only)
        if has_cat_type:
            cat_type = r.get(CAT_TYPE_COL)
            if pd.notna(cat_type) and str(cat_type).strip() in POST_REFRACTIVE_VALUES:
                continue
        cct = r.get("CCT", r.get("cct"))
        if pd.isna(cct):
            continue
        cct = float(cct)
        if cct < 1:
            cct = cct * 1000
        lt = r.get("LT", r.get("lt"))
        if pd.isna(lt):
            continue
        lt = float(lt)
        if lt < 1:
            continue
        al = r.get("AL", r.get("al"))
        acd = r.get("ACD", r.get("acd"))
        k1 = r.get("K1", r.get("k1"))
        k2 = r.get("K2", r.get("k2"))
        w2w = r.get("W2W", r.get("wtw"))
        a_const = r.get("A_Constant", r.get("a_constant"))
        model = r.get("晶体型号", r.get("model"))
        if pd.isna(al) or pd.isna(k1) or pd.isna(k2) or pd.isna(a_const):
            continue
        al_f = float(al)
        if pd.isna(model) or str(model).strip() == "":
            model = "SN60WF"
        target = r.get("预留", r.get("target", 0.0))
        if pd.isna(target):
            target = 0.0
        target = float(target)
        if target < -2.5:
            target = -2.5
        elif target > 1.0:
            target = 1.0
        eye = str(r.get("眼别", "OD")).strip().upper()
        if eye not in ("OD", "OS"):
            continue
        if pd.isna(w2w):
            w2w = 12.0
        if pd.isna(acd):
            continue
        pid = r.get("ID", "unknown")
        if pd.isna(pid):
            pid = "unknown"
        pid = str(pid).strip()
        if (pid, eye) in done_keys:
            continue
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
        patient = {
            "id_email": f"{pid}@local",
            "name": pid[:20] if len(pid) > 20 else pid,
            "first_name": "P",
            "dob": dob,
            "gender": g,
        }
        eye_data = {
            "target_refr": f"{target:.2f}",
            "al": f"{float(al):.2f}",
            "cct": str(int(round(cct))),
            "acd": f"{float(acd):.2f}",
            "lt": f"{float(lt):.2f}",
            "k1": f"{float(k1):.2f}",
            "k1_axis": K1_AXIS_DEFAULT,
            "k2": f"{float(k2):.2f}",
            "k2_axis": K2_AXIS_DEFAULT,
            "n": DEFAULT_N,
            "wtw": f"{float(w2w):.1f}",
        }
        iol = {
            "manufacturer": model_to_manufacturer(model),
            "model": str(model).strip(),
            "a_constant": f"{float(a_const):.2f}",
        }
        payload = {
            "row_index": i + 1,
            "id": pid,
            "eye": eye,
            "patient": patient,
            "eye_side": eye.lower(),
            "eye_data": eye_data,
            "iol": iol,
        }
        # Classify: high myopia (AL>=26 or 白内障类型 contains 高度近视) vs ordinary cataract
        is_high_myopia = False
        if has_cat_type:
            ct = r.get(CAT_TYPE_COL)
            if pd.notna(ct):
                ct_str = str(ct).strip()
                if "高度近视" in ct_str:
                    is_high_myopia = True
        if not is_high_myopia and al_f >= HIGH_MYOPIA_AL_MM:
            is_high_myopia = True
        if is_high_myopia:
            high_myopia_candidates.append(payload)
        else:
            ordinary_candidates.append(payload)

    if args.all:
        out = high_myopia_candidates + ordinary_candidates
        n_high = len(high_myopia_candidates)
        n_ordinary = len(ordinary_candidates)
    else:
        # Stratified sample: up to target_total, evenly from high myopia and ordinary (half each)
        half = target_total // 2
        rng = random.Random(RANDOM_SEED)
        n_high = min(half, len(high_myopia_candidates))
        n_ordinary = min(half, len(ordinary_candidates))
        out_high = rng.sample(high_myopia_candidates, n_high) if n_high else []
        out_ordinary = rng.sample(ordinary_candidates, n_ordinary) if n_ordinary else []
        out = out_high + out_ordinary
        rng.shuffle(out)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Non-refractive-surgery: high myopia {len(high_myopia_candidates)}, ordinary {len(ordinary_candidates)}")
    mode = "all" if args.all else "sampled"
    print(f"{mode}: high myopia {n_high}, ordinary {n_ordinary}, total {len(out)} -> {out_json}")


if __name__ == "__main__":
    main()
