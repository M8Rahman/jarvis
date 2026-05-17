"""
core/intent.py
──────────────
Converts raw transcribed text (English) into an Action.

Phase 1.3 changes:
  - ALL Bangla text removed. English only throughout.
  - Synonym groups expanded for natural English variations
  - Collection PO intent now catches more natural phrasings:
      "Find Cecil Collection 10.2"
      "Search Cecil coll 10.2"
      "Open order sheet for Cecil 10.2"
      "Find collection 10.2"
  - Filler words updated to English-only
  - Descriptions updated to English-only

Adding a new command:
  1. Add IntentRule to INTENT_RULES (or extend an existing one's keywords).
  2. Add handler in core/executor.py.
  Done. No retraining. No model updates.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger("jarvis.intent")


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Action:
    name:   str
    params: dict = field(default_factory=dict)
    raw:    str  = ""

    def describe(self) -> str:
        return _DESCRIPTIONS.get(self.name, self.name)


@dataclass
class IntentRule:
    keywords:  list[str]
    name:      str
    extractor: Callable[[str], dict] | None = None
    priority:  int = 0


# ── Human-readable descriptions (English only) ────────────────────────────────
_DESCRIPTIONS: dict[str, str] = {
    "find_collection_po":  "Search Outlook for collection PO email",
    "po_entry":            "Open PO Entry form in ERP",
    "cutting_report":      "Open Cutting Report in ERP",
    "production_report":   "Generate Production Report in ERP",
    "google_search":       "Search Google",
    "open_outlook":        "Open Outlook",
    "open_erp":            "Open ERP",
    "take_screenshot":     "Take a screenshot",
}


# ── Text normalisation ────────────────────────────────────────────────────────

# Filler words to strip before matching (English only)
_FILLERS = {
    "please", "can you", "could you", "would you", "jarvis",
    "hey", "ok", "okay", "now", "just", "me",
}

# Synonym groups — all terms in a group treated as the first (canonical) form
_SYNONYMS: list[tuple[str, ...]] = [
    # find/search/open/look-up
    (
        "find", "search", "locate", "get", "fetch", "show", "look for",
        "look up", "pull up", "pull", "open", "launch", "start", "load",
    ),
    # collection synonyms
    (
        "collection", "coll", "col",
    ),
    # outlook/email synonyms
    (
        "outlook", "mail", "email", "inbox",
    ),
    # point/dot for decimal
    (
        "point", "dot", ".",
    ),
    # order sheet synonyms
    (
        "order sheet", "order", "sheet",
    ),
]


def _normalise(text: str) -> str:
    """
    Lowercase, strip punctuation (except dots in numbers),
    remove fillers, expand synonyms, collapse whitespace.
    """
    t = text.lower().strip()

    # Strip punctuation except digits, letters, dot, hyphen
    t = re.sub(r"[^\w\s.\-]", " ", t)

    # Remove filler words
    for filler in _FILLERS:
        t = re.sub(r"\b" + re.escape(filler) + r"\b", " ", t)

    # Expand synonyms: replace every synonym with canonical (first) form
    for group in _SYNONYMS:
        canonical = group[0]
        for synonym in group[1:]:
            t = re.sub(r"\b" + re.escape(synonym) + r"\b", canonical, t)

    t = re.sub(r"\s+", " ", t).strip()
    return t


# ── Param extractors ──────────────────────────────────────────────────────────

def _extract_collection_po(text: str) -> dict:
    """
    Extract buyer name, collection number, and optional PO number
    from a normalised English command.

    Examples (after normalisation):
      "find cecil collection 10.2"
        → buyer="Cecil", coll_encoded="102"
      "find collection 10.2"
        → buyer="", coll_encoded="102"   (no buyer specified)
      "find cecil collection 10.2 po 325978"
        → buyer="Cecil", coll_encoded="102", po_number="325978"
    """
    from core.buyer_registry import buyer_registry

    params: dict = {}

    # ── Buyer resolution ──────────────────────────────────────────────────
    for alias in buyer_registry.all_aliases():
        if alias in text:
            buyer = buyer_registry.resolve(alias)
            if buyer:
                params["buyer"] = buyer.name
                break

    # ── Collection number ─────────────────────────────────────────────────
    # Matches: "collection 10.2", "collection 10 point 2", "collection 102"
    # After normalisation "coll" → "collection", "point" → "point" (already canonical)
    coll_match = re.search(
        r"\bcollection\b\s*(\d{1,3}(?:[.\s]?\d)?)",
        text,
    )
    if coll_match:
        raw_coll = coll_match.group(1).strip()
        encoded  = buyer_registry.encode_collection(raw_coll)
        params["coll_encoded"] = encoded

    # ── PO number ────────────────────────────────────────────────────────
    po_match = re.search(r"\bpo\b\s*(?:number\s*)?(\d{5,10})", text)
    if po_match:
        params["po_number"] = po_match.group(1)

    return params


def _extract_search_query(text: str) -> dict:
    """Pull search term from Google search commands."""
    for kw in ("google", "search", "find"):
        idx = text.find(kw)
        if idx != -1:
            remainder = text[idx + len(kw):].strip()
            if remainder:
                return {"query": remainder}
    return {}


def _extract_report_date(text: str) -> dict:
    if any(w in text for w in ["yesterday", "kal"]):
        return {"date": "yesterday"}
    if any(w in text for w in ["today", "aaj"]):
        return {"date": "today"}
    return {}


# ── Intent rules ──────────────────────────────────────────────────────────────

INTENT_RULES: list[IntentRule] = [

    # ── Outlook / Collection PO search (highest priority — most specific) ──
    # Matches any command containing "collection" (the canonical synonym for
    # coll/col) after normalisation, plus an optional buyer name and number.
    # Examples after normalisation:
    #   "find cecil collection 10.2"         ← direct
    #   "find collection 10.2"               ← no buyer
    #   "find order sheet for cecil 10.2"    ← "order sheet" synonym
    #   "search cecil coll 10.2"             ← coll→collection canonical
    IntentRule(
        keywords=["collection"],
        name="find_collection_po",
        extractor=_extract_collection_po,
        priority=20,
    ),

    # ── ERP workflows ──────────────────────────────────────────────────────
    IntentRule(
        keywords=["po entry", "purchase order entry", "open po"],
        name="po_entry",
        priority=10,
    ),
    IntentRule(
        keywords=["cutting report"],
        name="cutting_report",
        extractor=_extract_report_date,
        priority=10,
    ),
    IntentRule(
        keywords=["production report"],
        name="production_report",
        extractor=_extract_report_date,
        priority=9,
    ),
    IntentRule(
        keywords=["open erp", "erp open", "erp start", "launch erp", "start erp"],
        name="open_erp",
        priority=8,
    ),

    # ── Outlook (generic open — lower priority than collection search) ──────
    IntentRule(
        keywords=["open outlook", "start outlook", "launch outlook",
                  "outlook open", "open mail", "open email"],
        name="open_outlook",
        priority=7,
    ),

    # ── Browser ────────────────────────────────────────────────────────────
    IntentRule(
        keywords=["google", "search google", "google search"],
        name="google_search",
        extractor=_extract_search_query,
        priority=6,
    ),

    # ── Utility ────────────────────────────────────────────────────────────
    IntentRule(
        keywords=["screenshot", "screen shot", "take screenshot"],
        name="take_screenshot",
        priority=5,
    ),
]


# ── Engine ────────────────────────────────────────────────────────────────────

class IntentEngine:

    def __init__(self):
        self._rules = sorted(INTENT_RULES, key=lambda r: r.priority, reverse=True)
        log.info("IntentEngine ready — %d rules.", len(self._rules))

    def parse(self, raw_text: str) -> Action | None:
        normalised = _normalise(raw_text)
        log.debug("Normalised: %r", normalised)

        for rule in self._rules:
            if self._matches(normalised, rule.keywords):
                params = rule.extractor(normalised) if rule.extractor else {}
                action = Action(name=rule.name, params=params, raw=raw_text)
                log.info("Intent: %s | params=%s", rule.name, params)
                return action

        log.warning("No intent matched: %r", raw_text)
        return None

    @staticmethod
    def _matches(text: str, keywords: list[str]) -> bool:
        return any(kw.lower() in text for kw in keywords)
