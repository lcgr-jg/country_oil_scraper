from pathlib import Path
import re

text = Path("_are_page.html").read_text(encoding="utf-8")
for pat in [r'[^"\']+\.xlsx?', r'\\u[\da-f]{4}', r'paliw[^"\']{0,80}', r'/files/[^"\']+', r'cms[^"\']{0,100}']:
    hits = re.findall(pat, text, re.I)
    print(pat, len(hits))
    for h in sorted(set(hits))[:20]:
        print(" ", h[:150])

# find escaped xlsx
idx = text.find("xlsx")
while idx != -1 and idx < 500000:
    print("CTX", repr(text[max(0,idx-80):idx+120]))
    idx = text.find("xlsx", idx+1)
    if idx > 450000:
        break
