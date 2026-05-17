"""
workflows/outlook_workflows.py
───────────────────────────────
Outlook automation via win32com — COM object model, not UI clicking.

Phase 1.3 upgrades:
  - Bangla text removed entirely
  - INTELLIGENT EMAIL MATCHING replacing simple keyword AND-match:
      Old: required ALL keywords present in subject → missed real emails
      New: scoring system that ranks candidates by relevance
  - _score_subject() — deterministic scoring function:
      + points for collection code present
      + points for buyer name present
      + points for "order sheet" / "coll" signals
      − penalties for RE:/FW: prefixes, noise phrases
      Ties broken by received date (newest wins)
  - _find_best_collection_email() replaces _find_collection_email()
  - Subject normalisation before scoring
  - Result is logged with score for debugging

Attachment save path:
  E:/Projects/JARVIS/attachments/{Buyer}/{collection_code}/{filename}.pdf
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from datetime import datetime

from config.settings import settings
from core.buyer_registry import buyer_registry, Buyer
from core.executor import OK, FAIL, ExecutionResult
from core.memory import memory

log = logging.getLogger("jarvis.workflows.outlook")


# ══════════════════════════════════════════════════════════════════════════════
#  SUBJECT SCORING ENGINE
#  Deterministic, lightweight, no external dependencies.
# ══════════════════════════════════════════════════════════════════════════════

# Phrases that indicate a follow-up / noise email — penalise but don't exclude
_FOLLOWUP_PHRASES = [
    "add new quantity", "revised", "updated", "correction", "amendment",
    "change", "update", "modify", "additional",
]

# Email thread prefixes — lower priority than originals
_THREAD_PREFIXES = ["re:", "fw:", "fwd:", "re :", "fw :", "fwd :"]


def _normalise_subject(subject: str) -> str:
    """Lowercase, collapse whitespace, strip leading thread prefixes."""
    s = subject.lower().strip()
    # Remove leading RE:/FW: chains
    while True:
        stripped = s
        for prefix in _THREAD_PREFIXES:
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):].strip()
        if stripped == s:
            break
        s = stripped
    return re.sub(r"\s+", " ", s)


def _score_subject(subject: str, collection_code: str, buyer: Buyer) -> int:
    """
    Score an email subject for relevance to a collection search.
    Higher score = better match. Returns 0 if definitely not a match.

    Scoring breakdown:
      +100  collection code present (e.g. "2026102")  — REQUIRED signal
      + 30  "order sheet" in subject
      + 20  "coll" or "collection" in subject
      + 15  buyer name in subject
      +  5  clean original (no RE/FW prefix)
      -  5  is a reply (RE:) or forward (FW:)
      - 10  contains follow-up noise phrases (revised, add new quantity, etc.)

    Returns 0 if the collection code is NOT present — this is the hard gate.
    Everything else is soft scoring.
    """
    norm = _normalise_subject(subject)
    original_lower = subject.lower().strip()

    # ── Hard gate: collection code must appear ────────────────────────────
    if collection_code not in norm and collection_code not in original_lower:
        return 0

    score = 100  # base: collection code matched

    # ── Positive signals ──────────────────────────────────────────────────
    if "order sheet" in norm:
        score += 30
    if "coll" in norm or "collection" in norm:
        score += 20
    if buyer.name.lower() in norm:
        score += 15

    # ── Thread prefix penalty ─────────────────────────────────────────────
    original_norm = original_lower.strip()
    is_thread = any(original_norm.startswith(p) for p in _THREAD_PREFIXES)
    if not is_thread:
        score += 5       # reward clean originals
    else:
        score -= 5       # penalise RE/FW

    # ── Follow-up noise penalty ───────────────────────────────────────────
    for phrase in _FOLLOWUP_PHRASES:
        if phrase in norm:
            score -= 10
            break   # one penalty max — don't double-penalise

    return score


def _find_best_collection_email(items, buyer: Buyer, collection_code: str,
                                max_search: int = 200):
    """
    Scan inbox items, score each subject, return the highest-scoring email.

    Tie-breaking: if two emails have the same score, prefer the newer one
    (ReceivedTime descending — which is already how items are sorted).

    Returns the best email COM object, or None if no match found.
    """
    best_email = None
    best_score = 0
    best_subject = ""
    count = 0

    try:
        for item in items:
            if count >= max_search:
                break
            count += 1
            try:
                subj  = item.Subject or ""
                score = _score_subject(subj, collection_code, buyer)
                if score > 0:
                    log.debug(
                        "Candidate [score=%d]: %r", score, subj[:80]
                    )
                if score > best_score:
                    best_score   = score
                    best_email   = item
                    best_subject = subj
            except Exception:
                continue
    except Exception as exc:
        log.error("Error iterating inbox: %s", exc)

    if best_email:
        log.info(
            "Best match [score=%d] after scanning %d emails: %r",
            best_score, count, best_subject[:100],
        )
    else:
        log.info("No matching email found after scanning %d emails.", count)

    return best_email


# ══════════════════════════════════════════════════════════════════════════════
#  COM HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _get_outlook_app():
    try:
        import win32com.client
        return win32com.client.Dispatch("Outlook.Application")
    except Exception as exc:
        log.error("Cannot connect to Outlook COM: %s", exc)
        return None


def _ensure_outlook_running() -> bool:
    import win32com.client
    try:
        win32com.client.Dispatch("Outlook.Application")
        return True
    except Exception:
        pass
    log.info("Launching Outlook...")
    subprocess.Popen(["start", "outlook"], shell=True)
    time.sleep(settings.float("outlook_launch_wait", 4.0))
    try:
        win32com.client.Dispatch("Outlook.Application")
        return True
    except Exception as exc:
        log.error("Outlook still not available: %s", exc)
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  OPEN OUTLOOK
# ══════════════════════════════════════════════════════════════════════════════

def open_outlook() -> ExecutionResult:
    import pygetwindow as gw
    wins = [w for w in gw.getAllWindows() if "outlook" in w.title.lower()]
    if wins:
        try:
            wins[0].activate()
            return OK("Outlook is open.")
        except Exception:
            pass
    subprocess.Popen(["start", "outlook"], shell=True)
    time.sleep(settings.float("outlook_launch_wait", 4.0))
    return OK("Outlook is starting.")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN WORKFLOW: find_collection_po
# ══════════════════════════════════════════════════════════════════════════════

def find_collection_po(params: dict) -> ExecutionResult:
    """
    Find the best-matching collection email → save PDFs → open email/PDF.

    params:
      buyer        "Cecil"
      coll_encoded "102"        (collection 10.2 encoded)
      po_number    "325978"     (optional — open specific PO PDF)

    Matching strategy:
      Scores every email subject against the collection code using
      _score_subject(). Highest scorer wins. Tie → newer email.
      See _score_subject() for full scoring breakdown.

    Example subject matches for collection_code="2026102":
      "Order sheet of coll 2026102"              → score ~170  ← BEST
      "Order sheet of coll 2026102 add new qty"  → score ~160
      "RE: Order sheet of coll 2026102"          → score ~160
      "FW: Some other update 2026102"            → score ~115
    """
    start_ms = int(time.time() * 1000)

    buyer_name   = params.get("buyer", "")
    coll_encoded = params.get("coll_encoded", "")
    po_number    = params.get("po_number", "")

    if not buyer_name:
        return FAIL("Please say the buyer name. Example: Find Cecil Collection 10.2")
    if not coll_encoded:
        return FAIL("Please say the collection number. Example: Find Cecil Collection 10.2")

    buyer = buyer_registry.resolve(buyer_name)
    if not buyer:
        return FAIL(
            f"Buyer '{buyer_name}' is not in buyers.yaml. Please add it first."
        )
    if not buyer.has_order_type("collection"):
        return FAIL(
            f"Buyer '{buyer.name}' does not have collection order type configured."
        )

    year            = datetime.now().year
    collection_code = buyer_registry.build_collection_code(year, coll_encoded)
    log.info(
        "Collection search: buyer=%s  code=%s  po=%s",
        buyer.name, collection_code, po_number or "any",
    )

    if not _ensure_outlook_running():
        return FAIL("Could not start Outlook.")

    outlook = _get_outlook_app()
    if not outlook:
        return FAIL("Could not connect to Outlook.")

    try:
        namespace = outlook.GetNamespace("MAPI")
        inbox     = namespace.GetDefaultFolder(6)
        items     = inbox.Items
        items.Sort("[ReceivedTime]", True)   # newest first
    except Exception as exc:
        log.exception("Inbox access failed: %s", exc)
        return FAIL(f"Could not open Inbox: {exc}")

    matched = _find_best_collection_email(
        items, buyer, collection_code,
        max_search=settings.int("outlook_max_search", 200),
    )

    if matched is None:
        memory.log_command(
            str(params), "find_collection_po", False, params, "email not found"
        )
        return FAIL(
            f"No email found for {buyer.name} collection {coll_encoded} "
            f"(looking for code {collection_code} in subject)."
        )

    # ── Save PDF attachments ──────────────────────────────────────────────
    save_dir = os.path.join(
        settings.str("attachment_root"), buyer.name, collection_code
    )
    os.makedirs(save_dir, exist_ok=True)
    saved_files, po_numbers = _save_pdf_attachments(matched, save_dir, collection_code)

    # ── Build spoken summary ──────────────────────────────────────────────
    try:
        received_str = matched.ReceivedTime.strftime("%d %B %Y")
    except Exception:
        received_str = "unknown date"

    if po_numbers:
        po_list_spoken = f"{len(po_numbers)} PO found: " + ", ".join(po_numbers)
    else:
        po_list_spoken = "No PO PDFs found in this email."

    summary = (
        f"Found email from {matched.SenderName}. "
        f"Received {received_str}. {po_list_spoken}"
    )

    duration_ms = int(time.time() * 1000) - start_ms
    memory.log_workflow(
        "find_collection_po",
        {**params, "collection_code": collection_code, "pos_found": po_numbers},
        True, duration_ms,
    )
    memory.log_command(str(params), "find_collection_po", True, params)

    # ── Display email in Outlook ──────────────────────────────────────────
    try:
        matched.Display()
    except Exception as e:
        log.warning("Could not display email in Outlook: %s", e)

    # ── Open specific PO PDF if requested ─────────────────────────────────
    if po_number:
        if po_number in po_numbers:
            pdf_path = os.path.join(save_dir, f"{collection_code}-{po_number}.pdf")
            if os.path.exists(pdf_path):
                _open_file(pdf_path)
                summary += f" Opening PO {po_number}."
            else:
                summary += f" PO {po_number} PDF not found on disk."
        else:
            summary += f" PO {po_number} was not in this email."

    return OK(summary)


# ══════════════════════════════════════════════════════════════════════════════
#  INTERNAL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _save_pdf_attachments(email, save_dir: str, coll_code: str):
    saved_files: list[str] = []
    po_numbers:  list[str] = []
    try:
        atts = email.Attachments
        for i in range(atts.Count):
            att  = atts.Item(i + 1)
            name = att.FileName or ""
            if not name.lower().endswith(".pdf"):
                continue
            dest = os.path.join(save_dir, name)
            if not os.path.exists(dest):
                att.SaveAsFile(dest)
                log.info("Saved attachment: %s", dest)
            else:
                log.debug("Attachment already exists: %s", dest)
            saved_files.append(dest)
            parsed = buyer_registry.parse_po_from_filename(name)
            if parsed:
                _, po_num = parsed
                po_numbers.append(po_num)
    except Exception as exc:
        log.exception("Error saving attachments: %s", exc)
    log.info("Saved %d PDF(s) | POs: %s", len(saved_files), po_numbers)
    return saved_files, po_numbers


def _open_file(path: str):
    try:
        os.startfile(path)
    except Exception as exc:
        log.error("Could not open file %s: %s", path, exc)


def find_latest_buyer_po() -> ExecutionResult:
    """Legacy stub — guides user to correct syntax."""
    return FAIL(
        "Please specify buyer and collection number. "
        "Example: Find Cecil Collection 10.2"
    )
