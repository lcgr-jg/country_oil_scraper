"""
Scrapers package for country_oil_scraper.

Exports:
- IndiaPPACScraper:        Scraper for India's PPAC (Petroleum Planning & Analysis Cell)
- JodiScraper:             Scraper for the JODI-Oil World Database (primary & secondary)
- AustraliaAPStatScraper:  Scraper for Australia's DCCEEW Petroleum Statistics

Note on `AustraliaAPStatScraper`:
    Imported lazily via ``__getattr__`` because it depends on ``curl_cffi``
    (required to bypass energy.gov.au's TLS-fingerprinting WAF — see the
    module docstring in ``australia_apstat.py``). Eagerly importing it here
    would make the whole ``scrapers`` package fail to import in environments
    without curl_cffi, breaking the unrelated PPAC and JODI scripts. With
    lazy loading, ``from scrapers import JodiScraper`` works regardless,
    and ``from scrapers import AustraliaAPStatScraper`` only fires the
    curl_cffi import (with a clear ModuleNotFoundError if missing) when
    the Australia scraper is actually used.
"""

from .india_ppac import IndiaPPACScraper
from .jodi import JodiScraper

__all__ = ['IndiaPPACScraper', 'JodiScraper', 'AustraliaAPStatScraper']


def __getattr__(name):
    """PEP 562 module-level lazy attribute access for optional deps."""
    if name == "AustraliaAPStatScraper":
        from .australia_apstat import AustraliaAPStatScraper as _cls
        return _cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
