import re
from pathlib import Path

text = Path("_are_page.html").read_text(encoding="utf-8")
paths = sorted(set(re.findall(r"/uploads/Biuletyn_[^\"\\]+", text)))
out = Path("_are_biuletyn_paths.txt")
out.write_text("\n".join(paths), encoding="utf-8")
print("count", len(paths))
print("latest", paths[-10:])

# find full URLs if any
full = sorted(set(re.findall(r"https://[^\"\\]+Biuletyn[^\"\\]+", text)))
print("full urls", len(full))
for u in full[:5]:
    print(u)

# search for strapi/cms base
for token in ["strapi", "cms.are", "assets.are", "NEXT_PUBLIC", "uploads/"]:
    i = text.find(token)
    print(token, i)
