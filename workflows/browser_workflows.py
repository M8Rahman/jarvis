"""
workflows/browser_workflows.py
───────────────────────────────
Browser automation — uses the default Windows browser via webbrowser module.
No Playwright/Selenium dependency needed for Phase 1 simple search.

Phase 2 upgrade: swap webbrowser for playwright for full automation.
"""

import logging
import urllib.parse
import webbrowser

from core.executor import OK, FAIL, ExecutionResult

log = logging.getLogger("jarvis.workflows.browser")


def google_search(query: str) -> ExecutionResult:
    """Open the default browser with a Google search for `query`."""
    if not query.strip():
        return FAIL("Search query is empty.")
    encoded = urllib.parse.quote_plus(query)
    url     = f"https://www.google.com/search?q={encoded}"
    log.info("Opening Google search: %s", url)
    webbrowser.open(url)
    return OK(f"'{query}' Google-এ search করা হচ্ছে।")
