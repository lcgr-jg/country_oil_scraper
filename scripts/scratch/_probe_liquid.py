import re
import requests

text = requests.get(
    "https://www.are.waw.pl/pl/badania-statystyczne/wynikowe-informacje-statystyczne",
    headers={"User-Agent": "x"},
    timeout=60,
).text
paths = sorted(set(re.findall(r"/uploads/[^\"\\]+?\.(?:xls|xlsx)", text, re.I)))
keys = ("paliw", "paliiw", "ciek", "Biuletyn", "inf_")
for k in keys:
    hits = [p for p in paths if k.lower() in p.lower()]
    print(k, len(hits))
    for p in hits[:5]:
        print(" ", p)
    if len(hits) > 5:
        print(" ...")
        for p in hits[-3:]:
            print(" ", p)
