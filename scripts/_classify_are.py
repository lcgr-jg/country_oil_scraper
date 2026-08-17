"""Classify downloadable ARE xls by sheet signature."""
from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd
import requests

CMS = "https://cms.are.waw.pl"
HTML = Path(__file__).with_name("_are_page.html").read_text(encoding="utf-8")
paths = sorted(set(re.findall(r"/uploads/[^\"\\]+?\.xls", HTML, re.I)))
cands = [
    p
    for p in paths
    if "Biuletyn_" in p
    or re.search(r"/inf_\d{4}_", p, re.I)
    or "rynku_pal" in p.lower()
]

liquid: list[str] = []
other: list[str] = []
for path in cands:
    head = requests.head(CMS + path, headers={"User-Agent": "x"}, timeout=30)
    if head.status_code != 200:
        continue
    content = requests.get(CMS + path, headers={"User-Agent": "x"}, timeout=120).content
    if content[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        other.append(path + " (not xls)")
        continue
    xl = pd.ExcelFile(io.BytesIO(content))
    names = " ".join(xl.sheet_names).lower()
    if "tab 1.1" in names or "production of liquid fuels" in names:
        liquid.append(path)
    elif any(s in names for s in ("1.1", "tab 1.1")) and "czesc" in names:
        liquid.append(path)
    else:
        other.append(path + " :: " + ",".join(xl.sheet_names[:4]))

print("liquid", len(liquid))
print("other live", len(other))
for p in liquid[:5]:
    print(" L", p)
for p in other[:8]:
    print(" O", p[:120])
