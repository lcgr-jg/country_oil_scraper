import re
from pathlib import Path
text = Path("_are_page.html").read_text(encoding="utf-8")
inf = sorted(set(re.findall(r"/uploads/inf_[^\"\\]+?\.xls", text, re.I)))
Path("_inf_paths.txt").write_text("\n".join(inf), encoding="utf-8")
print(len(inf))
