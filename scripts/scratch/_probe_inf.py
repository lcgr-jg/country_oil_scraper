import re
import requests

text = requests.get(
    "https://www.are.waw.pl/pl/badania-statystyczne/wynikowe-informacje-statystyczne",
    headers={"User-Agent": "x"},
    timeout=60,
).text
paths = sorted(set(re.findall(r"/uploads/[^\"\\]+?\.(?:xls|xlsx)", text, re.I)))
inf = [p for p in paths if re.search(r"/inf_\d{4}_", p, re.I)]
print("inf_ count", len(inf))
print("first", inf[0])
print("last", inf[-1])

# Korekta and errata - exclude
liquid = [
    p
    for p in paths
    if (
        "Biuletyn_" in p
        or re.search(r"/inf_\d{4}_", p, re.I)
        or "rynku_pal" in p.lower()
    )
    and "Korekta" not in p
    and "Errata" not in p
    and "errata" not in p
]
print("liquid candidate count", len(liquid))
