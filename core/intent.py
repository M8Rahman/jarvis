"""
core/intent.py
──────────────
Converts raw transcribed text (English / Bangla / Banglish) into an Action.

IMPROVEMENTS over Phase 1:
  - Full English command support ("Open Outlook", "Find Cecil collection 10.5")
  - Text normalisation before matching (removes filler, strips punctuation)
  - Buyer-aware extraction (reads buyer registry for live alias list)
  - Collection number extraction with encoding (10.5 → "105")
  - PO number extraction
  - Synonym expansion so "locate / find / search / খোঁজো" all match

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


# ── Human-readable descriptions ───────────────────────────────────────────────
_DESCRIPTIONS: dict[str, str] = {
    "find_collection_po":  "Outlook-এ collection PO খুঁজবো",
    "po_entry":            "ERP-তে PO Entry করবো",
    "cutting_report":      "Cutting Report খুলবো",
    "production_report":   "Production Report generate করবো",
    "google_search":       "Google-এ search করবো",
    "open_outlook":        "Outlook খুলবো",
    "open_erp":            "ERP খুলবো",
    "take_screenshot":     "Screenshot নেবো",
}


# ── Text normalisation ────────────────────────────────────────────────────────

# Filler words to strip before matching
_FILLERS = {
    "please", "can you", "could you", "would you", "jarvis",
    "আমাকে", "একটু", "দয়া করে", "তুমি", "তুই",
}

# Synonym groups — all terms in a group are treated as equivalent
_SYNONYMS: list[tuple[str, ...]] = [
    ("find", "search", "locate", "get", "fetch", "show", "look for",
     "খোঁজো", "খুঁজো", "বের করো", "দেখাও", "আনো"),
    ("open", "launch", "start", "চালু করো", "খুলো", "চালু"),
    ("collection", "coll", "কালেকশন", "col"),
    ("outlook", "mail", "মেইল", "ইমেইল", "email"),
    ("point", "দশমিক", "."),
]


def _normalise(text: str) -> str:
    """
    Lowercase, strip punctuation (except dots in numbers), remove fillers,
    expand synonyms, collapse whitespace.
    """
    t = text.lower().strip()

    # Strip punctuation except digits, letters, Bengali chars, dot, hyphen
    t = re.sub(r"[^\w\s.\-\u0980-\u09FF]", " ", t)

    # Remove filler words
    for filler in _FILLERS:
        t = re.sub(r"\b" + re.escape(filler) + r"\b", " ", t)

    # Expand synonyms: replace every synonym with the first (canonical) form
    for group in _SYNONYMS:
        canonical = group[0]
        for synonym in group[1:]:
            t = re.sub(r"\b" + re.escape(synonym) + r"\b", canonical, t)

    t = re.sub(r"\s+", " ", t).strip()
    return t


# ── Param extractors ──────────────────────────────────────────────────────────

def _extract_collection_po(text: str) -> dict:
    """
    Extract buyer name, collection number, and optional PO number.

    Examples (after normalisation):
      "find cecil collection 10.5"
        → buyer="Cecil", coll_encoded="105", collection_code="" (year added at runtime)
      "find cecil coll 10.5 po 325978"
        → buyer="Cecil", coll_encoded="105", po_number="325978"
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
    # Matches: "collection 10.5", "collection 10 point 5", "collection 105"
    coll_match = re.search(
        r"\bcollection\b\s*(\d{1,3}(?:[.\s]?\d)?)",
        text,
    )
    if coll_match:
        raw_coll = coll_match.group(1).strip()
        encoded  = buyer_registry.encode_collection(raw_coll)
        params["coll_encoded"] = encoded

    # ── PO number ────────────────────────────────────────────────────────
    # Matches: "po 325978", "po number 325978"
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
    if any(w in text for w in ["গতকাল", "yesterday", "kal"]):
        return {"date": "yesterday"}
    if any(w in text for w in ["আজ", "today", "aaj"]):
        return {"date": "today"}
    return {}


# ── Intent rules ──────────────────────────────────────────────────────────────

def _build_buyer_keywords() -> list[str]:
    """Dynamically build buyer keywords from registry so YAML drives matching."""
    try:
        from core.buyer_registry import buyer_registry
        return buyer_registry.all_aliases()
    except Exception:
        return []


INTENT_RULES: list[IntentRule] = [

    # ── Outlook / PO search (highest priority — most specific) ─────────────
    IntentRule(
        # Matches whenever we see "find/search" + a buyer name + "collection"
        # Built dynamically so adding buyers to YAML auto-adds keywords
        keywords=["collection"],          # broad anchor; extractor does fine work
        name="find_collection_po",
        extractor=_extract_collection_po,
        priority=20,
    ),

    # ── ERP workflows ──────────────────────────────────────────────────────
    IntentRule(
        keywords=["po entry", "po করো", "po দাও", "purchase order entry"],
        name="po_entry",
        priority=10,
    ),
    IntentRule(
        keywords=["cutting report", "cutting রিপোর্ট"],
        name="cutting_report",
        extractor=_extract_report_date,
        priority=10,
    ),
    IntentRule(
        keywords=["production report", "production রিপোর্ট"],
        name="production_report",
        extractor=_extract_report_date,
        priority=9,
    ),
    IntentRule(
        keywords=["open erp", "erp open", "erp start", "launch erp",
                  "erp চালু", "erp খুলো"],
        name="open_erp",
        priority=8,
    ),

    # ── Outlook (generic open — lower priority than collection search) ──────
    IntentRule(
        keywords=["open outlook", "start outlook", "launch outlook",
                  "outlook open", "outlook খুলো", "outlook চালু",
                  "outlook", "mail open", "open mail"],
        name="open_outlook",
        priority=7,
    ),

    # ── Browser ────────────────────────────────────────────────────────────
    IntentRule(
        keywords=["google", "search google", "google search",
                  "খোঁজো google", "সার্চ"],
        name="google_search",
        extractor=_extract_search_query,
        priority=6,
    ),

    # ── Utility ────────────────────────────────────────────────────────────
    IntentRule(
        keywords=["screenshot", "screen shot", "স্ক্রিনশট"],
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
