"""
core/intent.py
──────────────
Converts raw transcribed text (English) into an Action.

Phase 2.0 bug fixes:
  BUG 1 FIXED — Collection number encoding was broken.
    Root cause: _normalise() replaced '.' with 'point' via the SYNONYM group
    ('point', 'dot', '.'). This turned '10.2' into '10point2', which the
    collection regex then failed to parse, capturing only '10' → encoding
    to '100' instead of '102'.
    Fix: REMOVED '.' from the synonym group. Dots in numbers are preserved.
    The extractor now also works on the RAW text (not just normalised) to
    extract the collection number, avoiding normalisation side-effects.

  BUG 2 FIXED — Google search query was corrupted.
    Root cause: 'search' is a synonym for 'find'. After normalisation,
    "Google search for Kylie Jenner" became "Google find for Kylie Jenner".
    The extractor then found 'find' as a keyword and returned the remainder
    including the word 'find', giving query="find for kylie jenner".
    Fix: extractor now strips known trigger words from the extracted query
    and works from the original RAW text for cleaner output.

  BUG 3 FIXED — "Open Outlook" intent inconsistently not matching.
    Root cause: 'open' is a synonym for 'find'. After normalisation,
    "Open Outlook" became "find outlook". The intent rule for open_outlook
    listed "open outlook" as a keyword but after normalisation the text
    is "find outlook". Added "find outlook" to the keyword list.

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
    extractor: Callable[[str, str], dict] | None = None   # (normalised, raw) -> dict
    priority:  int = 0


# ── Human-readable descriptions ───────────────────────────────────────────────
_DESCRIPTIONS: dict[str, str] = {
    "find_collection_po":  "Search Outlook for collection PO email",
    "po_entry":            "Open PO Entry form in ERP",
    "cutting_report":      "Open Cutting Report in ERP",
    "production_report":   "Generate Production Report in ERP",
    "google_search":       "Search Google",
    "open_outlook":        "Open Outlook",
    "open_erp":            "Open ERP",
    "take_screenshot":     "Take a screenshot",
    "extract_po_pdf":      "Extract data from PO PDF",
    "train_po_template":   "Train PDF extraction template",
}


# ── Text normalisation ────────────────────────────────────────────────────────

_FILLERS = {
    "please", "can you", "could you", "would you", "jarvis",
    "hey", "ok", "okay", "now", "just", "me",
}

# BUG FIX: Removed '.' from the point/dot synonym group.
# '.' in numbers (e.g. '10.2') must be preserved through normalisation.
# The extractor uses raw text for numeric parsing anyway.
_SYNONYMS: list[tuple[str, ...]] = [
    # find/search/open — all become 'find'
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
    # point/dot for decimal — but NOT '.' itself (that stays as-is in numbers)
    (
        "point", "dot",
    ),
    # order sheet synonyms
    (
        "order sheet", "order", "sheet",
    ),
]


def _normalise(text: str) -> str:
    """
    Lowercase, strip punctuation (except dots in numbers), remove fillers,
    expand synonyms, collapse whitespace.

    IMPORTANT: This function deliberately preserves '.' in numeric contexts
    (e.g., '10.2') by NOT including '.' in the synonym replacement list.
    """
    t = text.lower().strip()

    # Strip punctuation except digits, letters, dot, hyphen
    t = re.sub(r"[^\w\s.\-]", " ", t)

    # Remove filler words
    for filler in _FILLERS:
        t = re.sub(r"\b" + re.escape(filler) + r"\b", " ", t)

    # Expand synonyms
    for group in _SYNONYMS:
        canonical = group[0]
        for synonym in group[1:]:
            t = re.sub(r"\b" + re.escape(synonym) + r"\b", canonical, t)

    t = re.sub(r"\s+", " ", t).strip()
    return t


# ── Param extractors ──────────────────────────────────────────────────────────
# Extractors now receive BOTH normalised text AND raw text.
# Use normalised for keyword detection, raw for numeric/name extraction.

def _extract_collection_po(normalised: str, raw: str) -> dict:
    """
    Extract buyer name, collection number, and optional PO number.

    BUG FIX: Collection number is now extracted from RAW text, not normalised.
    This prevents the '10.2' → '10point2' corruption that caused '102' to
    be parsed as '10' → encoded to '100'.

    Examples:
      raw="Find Cecil Collection 10.2"    → buyer="Cecil", coll_encoded="102"
      raw="Find collection 10.2"          → buyer="", coll_encoded="102"
      raw="Find Cecil coll 10 point 2"    → buyer="Cecil", coll_encoded="102"
      raw="Find Cecil collection 10"      → buyer="Cecil", coll_encoded="100"
    """
    from core.buyer_registry import buyer_registry

    params: dict = {}

    # ── Buyer resolution (use normalised — aliases are already lowercase) ──
    for alias in buyer_registry.all_aliases():
        if alias in normalised:
            buyer = buyer_registry.resolve(alias)
            if buyer:
                params["buyer"] = buyer.name
                break

    # ── Collection number — extract from RAW text ─────────────────────────
    # Pattern 1: "10.2", "10.5" etc (decimal form)
    # Pattern 2: "10 point 2", "10 dot 2" (spoken decimal)
    # Pattern 3: "10", "11" (whole number)
    raw_lower = raw.lower()

    # Try spoken decimal first: "10 point 2" or "10 dot 2"
    spoken_match = re.search(
        r"\b(?:collection|coll|col)\s+(\d{1,3})\s+(?:point|dot)\s+(\d)",
        raw_lower,
    )
    if spoken_match:
        integer = spoken_match.group(1)
        decimal = spoken_match.group(2)
        raw_coll = f"{integer}.{decimal}"
    else:
        # Try numeric decimal: "collection 10.2"
        numeric_match = re.search(
            r"\b(?:collection|coll|col)\s+(\d{1,3}(?:\.\d)?)",
            raw_lower,
        )
        raw_coll = numeric_match.group(1) if numeric_match else None

    if raw_coll:
        encoded = buyer_registry.encode_collection(raw_coll)
        params["coll_encoded"] = encoded
        log.debug("Collection extracted from raw: %r → encoded: %r", raw_coll, encoded)

    # ── PO number ─────────────────────────────────────────────────────────
    po_match = re.search(r"\bpo\b\s*(?:number\s*)?(\d{5,10})", normalised)
    if po_match:
        params["po_number"] = po_match.group(1)

    return params


def _extract_search_query(normalised: str, raw: str) -> dict:
    """
    Extract Google search query from the raw text.

    BUG FIX: Previously used normalised text, which caused 'search' to be
    replaced by 'find', corrupting the extracted query. Now uses raw text
    and strips trigger words from the extracted portion.

    Examples:
      raw="Google search for Kylie Jenner" → query="Kylie Jenner"
      raw="Search Google for AI news"      → query="AI news"
      raw="Google Elon Musk"               → query="Elon Musk"
    """
    raw_lower = raw.lower().strip().rstrip(".")

    # Remove leading trigger patterns
    # Handles: "google search for X", "search google for X", "google X", "search for X"
    trigger_patterns = [
        r"^(?:google\s+)?search(?:\s+google)?(?:\s+for)?\s+",
        r"^google(?:\s+for)?\s+",
        r"^search(?:\s+for)?\s+",
    ]
    result = raw_lower
    for pattern in trigger_patterns:
        cleaned = re.sub(pattern, "", result, flags=re.IGNORECASE)
        if cleaned != result:
            result = cleaned
            break

    result = result.strip(" .")
    if result:
        # Preserve original casing from raw text
        # Find where result starts in raw (case-insensitive)
        idx = raw_lower.find(result)
        if idx != -1:
            result = raw[idx : idx + len(result)].strip()
        return {"query": result}
    return {}


def _extract_report_date(normalised: str, raw: str) -> dict:
    if any(w in normalised for w in ["yesterday", "kal"]):
        return {"date": "yesterday"}
    if any(w in normalised for w in ["today", "aaj"]):
        return {"date": "today"}
    return {}


def _extract_po_pdf(normalised: str, raw: str) -> dict:
    """Extract PDF file path or buyer name for PO extraction command."""
    params = {}
    # Look for file path pattern
    path_match = re.search(r'([a-z]:[\\\/][^\s]+\.pdf)', raw, re.IGNORECASE)
    if path_match:
        params["pdf_path"] = path_match.group(1)
    # Look for buyer name
    from core.buyer_registry import buyer_registry
    for alias in buyer_registry.all_aliases():
        if alias in normalised:
            buyer = buyer_registry.resolve(alias)
            if buyer:
                params["buyer"] = buyer.name
                break
    return params


# ── Intent rules ──────────────────────────────────────────────────────────────

INTENT_RULES: list[IntentRule] = [

    # ── Collection PO search (highest priority — most specific) ───────────
    IntentRule(
        keywords=["collection"],
        name="find_collection_po",
        extractor=_extract_collection_po,
        priority=20,
    ),

    # ── PO PDF extraction ─────────────────────────────────────────────────
    IntentRule(
        keywords=["extract po", "extract pdf", "read po", "read pdf", "scan po",
                  "process pdf", "extract purchase order"],
        name="extract_po_pdf",
        extractor=_extract_po_pdf,
        priority=18,
    ),

    # ── PDF template training ─────────────────────────────────────────────
    IntentRule(
        keywords=["train po", "train pdf", "teach pdf", "train template",
                  "train extraction", "label pdf"],
        name="train_po_template",
        extractor=_extract_po_pdf,
        priority=17,
    ),

    # ── ERP workflows ─────────────────────────────────────────────────────
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
        keywords=["open erp", "erp open", "erp start", "launch erp", "start erp",
                  "find erp"],
        name="open_erp",
        priority=8,
    ),

    # ── Outlook generic open ──────────────────────────────────────────────
    # BUG FIX: After normalisation, 'open' becomes 'find', so 'open outlook'
    # becomes 'find outlook'. Added 'find outlook' to keyword list.
    IntentRule(
        keywords=["open outlook", "find outlook", "start outlook", "launch outlook",
                  "outlook open", "open mail", "open email", "find mail",
                  "open inbox", "find inbox"],
        name="open_outlook",
        priority=7,
    ),

    # ── Browser ───────────────────────────────────────────────────────────
    IntentRule(
        keywords=["google", "search google", "google search"],
        name="google_search",
        extractor=_extract_search_query,
        priority=6,
    ),

    # ── Utility ───────────────────────────────────────────────────────────
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
        # Diagnostic: log all rules at startup
        for rule in self._rules:
            log.debug(
                "  Rule [priority=%d] %s — keywords: %s",
                rule.priority, rule.name, rule.keywords,
            )

    def parse(self, raw_text: str) -> Action | None:
        normalised = _normalise(raw_text)
        log.debug("Normalised: %r", normalised)

        for rule in self._rules:
            if self._matches(normalised, rule.keywords):
                # BUG FIX: Pass both normalised AND raw to extractor
                params = rule.extractor(normalised, raw_text) if rule.extractor else {}
                action = Action(name=rule.name, params=params, raw=raw_text)
                log.info("Intent: %s | params=%s", rule.name, params)
                return action

        log.warning("No intent matched: %r", raw_text)
        return None

    @staticmethod
    def _matches(text: str, keywords: list[str]) -> bool:
        return any(kw.lower() in text for kw in keywords)
