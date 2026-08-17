import pandas as pd
from pathlib import Path

p = Path("../data/raw/poland/are/Biuletyn_marzec_2026.xls")
df = pd.read_excel(p, sheet_name="tab 1.6__1.7__1.8", header=None)
lines = []
for i, row in df.iterrows():
    text = str(row[0]) if pd.notna(row[0]) else ""
    if "Tablica" in text or "Domestic consumption" in text or "Zużycie krajowe" in text:
        lines.append(f"{i}: {text[:100]} | {row[1:4].tolist()}")
Path("_tab1678.txt").write_text("\n".join(lines), encoding="utf-8")

df2 = pd.read_excel(p, sheet_name="tab 1.1__1. 2", header=None)
lines2 = []
for i, row in df2.iterrows():
    text = str(row[0]) if pd.notna(row[0]) else ""
    if any(k in text for k in ("Motor gasoline", "Diesel oils", "Heating oil", "Fuel oil", "LPG", "Tablica 1.2")):
        lines2.append(f"{i}: {text[:80]} | {row[1:4].tolist()}")
Path("_tab112.txt").write_text("\n".join(lines2), encoding="utf-8")
print("ok")
