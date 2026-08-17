"""Probe Taiwan 5-03 supply/transformation workbook."""
from pathlib import Path

import pandas as pd

p = Path("data/raw/taiwan/m_5-03石油產品供給與轉變(11504)_v113.xlsx")
out = Path("data/raw/taiwan/_probe_503.txt")
xl = pd.ExcelFile(p)
lines = [f"Sheets: {xl.sheet_names!r}"]
for sn in xl.sheet_names:
    df = pd.read_excel(p, sheet_name=sn, header=None)
    lines.append(f"\n=== {sn!r} shape={df.shape} ===")
    lines.append(df.iloc[:18, : min(12, df.shape[1])].to_string())
    if len(df) > 20:
        lines.append("...")
        lines.append(df.iloc[:, [0, min(9, df.shape[1] - 1)]].tail(8).to_string())
out.write_text("\n".join(lines), encoding="utf-8")
print(out)
