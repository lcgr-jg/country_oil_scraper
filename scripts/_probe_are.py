"""Probe ARE liquid fuels publication URLs."""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

URL = "https://www.are.waw.pl/pl/badania-statystyczne/wynikowe-informacje-statystyczne"
HEADERS = {"User-Agent": "country_oil_scraper/1.0 (ARE probe)"}
XLSX_RE = re.compile(r"https?://[^\s\"'<>]+\.xlsx?", re.I)
API_RE = re.compile(r"/api/[^\s\"'<>]+", re.I)


def main() -> None:
    resp = requests.get(URL, timeout=60, headers=HEADERS)
    print("status", resp.status_code, "len", len(resp.text))
    text = resp.text
    out = Path(__file__).with_name("_are_page.html")
    out.write_text(text, encoding="utf-8")
    print("wrote", out)

    xlsx = sorted(set(XLSX_RE.findall(text)))
    print("\nXLSX URLs:", len(xlsx))
    for u in xlsx[:30]:
        if "paliw" in u.lower() or "fuel" in u.lower() or "rynku" in u.lower():
            print(" *", u)
    for u in xlsx[:15]:
        print(" ", u)

    apis = sorted(set(API_RE.findall(text)))
    print("\nAPI paths:", len(apis))
    for a in apis[:40]:
        print(" ", a)

    idx = text.lower().find("informacja-statystyczna-o-rynku-paliw")
    if idx >= 0:
        snippet = text[idx : idx + 5000]
        snippet_path = Path(__file__).with_name("_are_snippet.txt")
        snippet_path.write_text(snippet, encoding="utf-8")
        print("\nwrote snippet", snippet_path)


if __name__ == "__main__":
    main()
