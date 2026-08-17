"""
Back-compat shim for the Phase-0 exploration notebook.

Production code lives in ``reference.germany``; this module re-exports the
same helpers so ``notebooks/27_germany_bafa_exploration.ipynb`` keeps working.
"""

from reference.germany import *  # noqa: F403
