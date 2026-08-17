from pathlib import Path

text = Path("_are_page.html").read_text(encoding="utf-8")
for token in ["cms.are", "cms.", "uploads/Biuletyn_marzec_2026"]:
    idx = text.find(token)
    Path(f"_ctx_{token.replace('/','_')}.txt").write_text(
        text[max(0, idx - 300) : idx + 500], encoding="utf-8"
    )
    print(token, idx)
