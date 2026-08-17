import io
import requests
import pandas as pd

for label, rel in [
    ("inf_0324", "/uploads/inf_0324_MARZEC_38c6921633.xls"),
    ("inf_1224", "/uploads/inf_1224_GRUDZIEN_76c1527377.xls"),
    ("Biuletyn", "/uploads/Biuletyn_marzec_2026_910593cea3.xls"),
]:
    b = requests.get(
        "https://cms.are.waw.pl" + rel,
        headers={"User-Agent": "x"},
        timeout=120,
    ).content
    xl = pd.ExcelFile(io.BytesIO(b))
    sheet = next(s for s in xl.sheet_names if s.strip().startswith("1.1") or "tab 1.1" in s)
    df = pd.read_excel(io.BytesIO(b), sheet_name=sheet, header=None, nrows=20)
    out = f"_{label}_sheet.txt"
    df.to_csv(out, index=False, header=False)
    print(label, sheet, "->", out)
