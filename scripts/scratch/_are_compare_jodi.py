import pandas as pd
from pathlib import Path

p = Path("../data/raw/poland/are/Biuletyn_marzec_2026.xls")
df = pd.read_excel(p, sheet_name="tab 1.4__1.5", header=None)
lines = []
for i, row in df.iterrows():
    s = str(row[0]) if pd.notna(row[0]) else ""
    if any(k in s.lower() for k in ("tablica", "zużycie", "domestic", "diesel", "lpg", "olej nap")):
        lines.append(f"{i}: {row.tolist()[:6]}")
Path("_are_sales_rows.txt").write_text("\n".join(lines), encoding="utf-8")

# compare JODI March 2026
import csv
jodi_path = Path("../data/raw/jodi/secondary/2026.csv")
if not jodi_path.exists():
    jodi_path = Path("../data/raw/jodi/secondaryyear2026.csv")
for row in csv.DictReader(jodi_path.open(encoding="utf-8")):
    if row["REF_AREA"] == "PL" and row["TIME_PERIOD"] == "2026-03" and row["UNIT_MEASURE"] == "KTONS" and row["ASSESSMENT_CODE"] == "1":
        if row["FLOW_BREAKDOWN"] in ("TOTDEMO", "REFGROUT", "TOTIMPSB", "CLOSTLV") and row["ENERGY_PRODUCT"] in ("GASOLINE", "GASDIES", "LPG"):
            print(row["ENERGY_PRODUCT"], row["FLOW_BREAKDOWN"], row["OBS_VALUE"])

print("ARE gasoline domestic", df.iloc[14, 4])  # Zużycie krajowe row
