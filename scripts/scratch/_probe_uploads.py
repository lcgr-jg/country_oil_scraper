import re
from pathlib import Path
import requests

text = requests.get(
    "https://www.are.waw.pl/pl/badania-statystyczne/wynikowe-informacje-statystyczne",
    headers={"User-Agent": "x"},
    timeout=60,
).text
paths = sorted(set(re.findall(r"/uploads/[^\"\\]+?\.(?:xls|xlsx)", text)))
print("total uploads", len(paths))
biuletyn = [p for p in paths if "Biuletyn_" in p]
other = [p for p in paths if "Biuletyn_" not in p]
print("biuletyn", len(biuletyn), "other", len(other))
for p in other[:30]:
    print(" OTHER", p)
# month slug pattern
months = {}
for p in biuletyn:
    m = re.search(r"Biuletyn_([a-z]+)_(\d{4})_", p, re.I)
    if m:
        months.setdefault(m.group(2), []).append(m.group(1))
print("years", sorted(months.keys()))
print("2024 months", sorted(set(months.get("2024", []))))
