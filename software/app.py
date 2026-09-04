# -*- coding: utf-8 -*-
"""
Web app for ML-based optimal IOL selection.
Run from project root: python software/app.py
Or: cd software && set PYTHONPATH=.. && python app.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import math
import flask

# Try to import ML module with error handling
try:
    from ml_optimal_iol import load_pipeline, find_five_iol_options
    _ml_import_error = None
except Exception as _e:
    load_pipeline = None
    find_five_iol_options = None
    _ml_import_error = str(_e)
    print("[ERROR] Failed to import ml_optimal_iol:", _e)

TEMPLATE_FOLDER = Path(__file__).resolve().parent / "templates"
app = flask.Flask(__name__, template_folder=str(TEMPLATE_FOLDER))
PIPELINE_PATH = ROOT / "results" / "ml_postSE_pipeline.joblib"


@app.route("/favicon.ico")
def favicon():
    """Avoid 404 when browser requests favicon."""
    return "", 204


@app.errorhandler(404)
def not_found(_):
    return flask.jsonify({"ok": False, "error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(e):
    """Return JSON and log the real error to the console."""
    import traceback
    traceback.print_exc()
    return flask.jsonify({"ok": False, "error": "Internal server error"}), 500

# Load pipeline once at startup
_pipeline = None
_pipeline_error = None


def get_pipeline():
    global _pipeline, _pipeline_error
    if _ml_import_error:
        raise ImportError("ML module import failed: " + _ml_import_error)
    if _pipeline is not None:
        return _pipeline
    if _pipeline_error is not None:
        raise _pipeline_error
    if not PIPELINE_PATH.exists():
        _pipeline_error = FileNotFoundError(
            "Pipeline not found: %s. Run: python ml_postSE_models.py --save-models" % PIPELINE_PATH
        )
        raise _pipeline_error
    try:
        _pipeline = load_pipeline(PIPELINE_PATH)
        return _pipeline
    except Exception as e:
        _pipeline_error = e
        raise


def pipeline_available():
    if _pipeline is not None:
        return True
    if PIPELINE_PATH.exists():
        return True
    return False


def get_available_models():
    try:
        p = get_pipeline()
        return list(p["models"].keys())
    except Exception:
        return []


@app.route("/")
def index():
    try:
        print("[DEBUG] index() called")
        # Check ML module import
        if _ml_import_error:
            print("[DEBUG] ML import error:", _ml_import_error)
            return flask.render_template(
                "index.html",
                models=[],
                pipeline_error="ML module import failed: " + _ml_import_error + ". Check dependencies."
            )
        
        print("[DEBUG] PIPELINE_PATH exists:", PIPELINE_PATH.exists())
        if not PIPELINE_PATH.exists():
            print("[DEBUG] Rendering without pipeline")
            return flask.render_template(
                "index.html",
                models=[],
                pipeline_error="Pipeline not found. Run from project root: python ml_postSE_models.py --save-models"
            )
        try:
            models = get_available_models()
            print("[DEBUG] Models loaded:", models)
            return flask.render_template("index.html", models=models, pipeline_error=None)
        except Exception as e:
            print("[DEBUG] Pipeline load failed:", e)
            return flask.render_template(
                "index.html",
                models=[],
                pipeline_error="Pipeline load failed: " + str(e)
            )
    except Exception as e:
        import traceback
        print("[DEBUG] Index error:", e)
        traceback.print_exc()
        return flask.render_template(
            "index.html",
            models=[],
            pipeline_error="Fatal error: " + str(e)
        )


def _float_or_none(x):
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


@app.route("/api/calculate", methods=["POST"])
def calculate():
    try:
        if _ml_import_error:
            return flask.jsonify({"ok": False, "error": "ML module import failed: " + _ml_import_error}), 503
        if not pipeline_available():
            try:
                get_pipeline()
            except Exception as e:
                return flask.jsonify({"ok": False, "error": str(e)}), 503
        data = flask.request.get_json(force=True, silent=True) or {}
        al = _float_or_none(data.get("AL"))
        if al is None:
            return flask.jsonify({"ok": False, "error": "AL is required."}), 400
        acd = _float_or_none(data.get("ACD"))
        lt = _float_or_none(data.get("LT"))
        cct = _float_or_none(data.get("CCT"))
        w2w = _float_or_none(data.get("W2W"))
        if w2w is None:
            w2w = _float_or_none(data.get("WTW"))
        k1 = _float_or_none(data.get("K1"))
        k2 = _float_or_none(data.get("K2"))
        reserve = _float_or_none(data.get("预留") or data.get("reserve"))
        if reserve is None:
            reserve = -0.5

        model_name = data.get("model") or "RandomForest"
        try:
            pipeline = get_pipeline()
        except Exception as e:
            return flask.jsonify({"ok": False, "error": "Pipeline load failed: " + str(e)}), 503
        if model_name not in pipeline["models"]:
            return flask.jsonify({"ok": False, "error": "Unknown model: " + model_name}), 400

        nan = math.nan
        biometry = {
            "AL": al,
            "ACD": acd if acd is not None else nan,
            "LT": lt if lt is not None else nan,
            "CCT": cct if cct is not None else nan,
            "W2W": w2w if w2w is not None else nan,
            "K1": k1 if k1 is not None else nan,
            "K2": k2 if k2 is not None else nan,
            "预留": reserve,
        }
        # Optional multimodal (pipeline imputer will handle if not in feat_cols)
        for key in ("B超", "A", "T", "N"):
            if key in data and data[key] not in (None, ""):
                try:
                    biometry[key] = float(data[key])
                except (TypeError, ValueError):
                    pass

        options = find_five_iol_options(
            biometry,
            target_SE=reserve,
            pipeline=pipeline,
            model_name=model_name,
            iol_bounds=(5.0, 35.0),
            iol_step=0.5,
        )
        return flask.jsonify({
            "ok": True,
            "target_se": reserve,
            "model": model_name,
            "options": options,
        })
    except Exception as e:
        return flask.jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
