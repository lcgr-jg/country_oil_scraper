import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
from reference import poland as p

path = ROOT / "data/raw/poland/are/Biuletyn_marzec_2026.xls"
xl = pd.ExcelFile(path)
sheet = p._find_sheet(xl.sheet_names, "tab 1.1")
df = pd.read_excel(path, sheet_name=sheet, header=None)
start, end = p._rows_for_table(df, "Table 1.1")
block = df.iloc[start:end].reset_index(drop=True)
lines = []
for i in range(len(block)):
    lines.append(
        f"{i}: col0={block.iloc[i, 0]!r} cols1-3={block.iloc[i, 1:4].tolist()}"
    )
open(ROOT / "scripts/_block11.txt", "w", encoding="utf-8").write("\n".join(lines))
