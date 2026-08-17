import pandas as pd
from pathlib import Path

p = Path("../data/raw/poland/are/Biuletyn_marzec_2026.xls")
xl = pd.ExcelFile(p)
lines = [f"sheets ({len(xl.sheet_names)}): {xl.sheet_names}\n"]
for s in xl.sheet_names:
    df = pd.read_excel(p, sheet_name=s, header=None)
    lines.append(f"\n=== {s} {df.shape} ===\n")
    lines.append(df.iloc[:15, :10].to_string())
    lines.append("\n")

Path("_are_inspect.txt").write_text("\n".join(lines), encoding="utf-8")
print("done")
