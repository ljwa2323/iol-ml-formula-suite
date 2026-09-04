# IOL ML Formula Suite

Machine learning training and traditional/AI IOL formula calculation toolkit for cataract refractive prediction.

## Contents

- `ml_postSE_models.py` / `ml_optimal_iol.py`: train post-SE models and optimize IOL power
- `iol_formulas.py` / `batch_iol_formulas.py`: SRK/T, Holladay 1, Haigis
- `batch_calculators/`: Kane, BUII, EVO, Hill-RBF batch callers
- `software/`: Flask web demo for ML IOL recommendation

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

## Notes

Code only. Data and trained model artifacts are not included.
