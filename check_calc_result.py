# Quick check of merged calc results (run from project root)
import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parent
path = BASE / "data" / "杨宁整合四文件合并_计算结果.xlsx"
df = pd.read_excel(path, sheet_name=0)

print("Shape:", df.shape)
print("Columns:", list(df.columns))
print()

cols = [c for c in df.columns if c in ("ID", "Recommended_IOL", "Calculation_Success", "IOL_Power_Table")]
if cols:
    print("Rows 678-682 (merge boundary):")
    print(df.loc[678:682, cols].to_string())
    print()
    print("Last 3 rows:")
    print(df[cols].tail(3).to_string())
print()
if "Calculation_Success" in df.columns:
    print("Calculation_Success True:", df["Calculation_Success"].eq(True).sum())
    print("Recommended_IOL non-null:", df["Recommended_IOL"].notna().sum())
