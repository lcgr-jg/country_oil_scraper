import json
import re
from pathlib import Path

text = Path("_are_page.html").read_text(encoding="utf-8")
# find liquid fuels section anchor and nearby JSON
idx = text.find("informacja-statystyczna-o-rynku-paliw-cieklych")
chunk = text[idx : idx + 80000]
# extract file objects
files = re.findall(
    r'\{"rok":(\d+),"okres":(\d+),"rodzaj":"(pdf|xls)"[^}]*?"url":"(/uploads/Biuletyn_[^"]+)"',
    chunk,
)
print("files in chunk", len(files))
for f in sorted(files, key=lambda x: (int(x[0]), int(x[1])))[-15:]:
    print(f)

# if zero, try broader search
all_files = re.findall(
    r'\{"rok":(\d+),"okres":(\d+),"rodzaj":"(pdf|xls)"[^}]*?"hash":"Biuletyn_[^"]+"[^}]*?"url":"(/uploads/Biuletyn_[^"]+)"',
    text,
)
print("all biuletyn metadata", len(all_files))
