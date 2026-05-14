"""
workflows/outlook_workflows.py
───────────────────────────────
Outlook automation via win32com — COM object model, not UI clicking.

Phase 1 capability: Collection PO search
  1. Connect to Outlook COM
  2. Search Inbox for collection email (buyer + collection code)
  3. Save all PDF attachments to structured folder on disk
  4. Speak results (sender, date, PO list)
  5. Open specific PO PDF if requested
  6. Display email in Outlook window

Attachment save path:
  E:/Projects/JARVIS/attachments/{Buyer}/{collection_code}/{filename}.pdf
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from datetime import datetime

from config.settings import settings
from core.buyer_registry import buyer_registry, Buyer
from core.executor import OK, FAIL, ExecutionResult
from core.memory import memory

log = logging.getLogger("jarvis.workflows.outlook")


# ── COM helpers ───────────────────────────────────────────────────────────────

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


# ── Open Outlook ──────────────────────────────────────────────────────────────

def open_outlook() -> ExecutionResult:
    import pygetwindow as gw
    wins = [w for w in gw.getAllWindows() if "outlook" in w.title.lower()]
    if wins:
        try:
            wins[0].activate()
            return OK("Outlook খোলা হয়েছে।")
        except Exception:
            pass
    subprocess.Popen(["start", "outlook"], shell=True)
    time.sleep(settings.float("outlook_launch_wait", 4.0))
    return OK("Outlook চালু হচ্ছে।")


# ── Main workflow ─────────────────────────────────────────────────────────────

def find_collection_po(params: dict) -> ExecutionResult:
    """
    Find collection email → save PDFs → open specific PO if requested.

    params:
      buyer        "Cecil"
      coll_encoded "105"       (collection 10.5 encoded)
      po_number    "325978"    (optional)
    """
    start_ms = int(time.time() * 1000)

    buyer_name   = params.get("buyer", "")
    coll_encoded = params.get("coll_encoded", "")
    po_number    = params.get("po_number", "")

    if not buyer_name:
        return FAIL("Buyer name বলুন। যেমন: Cecil collection 10.5")
    if not coll_encoded:
        return FAIL("Collection number বলুন। যেমন: collection 10.5")

    buyer = buyer_registry.resolve(buyer_name)
    if not buyer:
        return FAIL(f"'{buyer_name}' buyer config-এ নেই। buyers.yaml দেখুন।")
    if not buyer.has_order_type("collection"):
        return FAIL(f"{buyer.name} buyer-এর collection order config-এ নেই।")

    year            = datetime.now().year
    collection_code = buyer_registry.build_collection_code(year, coll_encoded)
    log.info("Search: buyer=%s  collection_code=%s  po=%s",
             buyer.name, collection_code, po_number or "any")

    if not _ensure_outlook_running():
        return FAIL("Outlook চালু করা যায়নি।")

    outlook = _get_outlook_app()
    if not outlook:
        return FAIL("Outlook connect করা যায়নি।")

    try:
        namespace = outlook.GetNamespace("MAPI")
        inbox     = namespace.GetDefaultFolder(6)
        items     = inbox.Items
        items.Sort("[ReceivedTime]", True)
    except Exception as exc:
        log.exception("Inbox access failed: %s", exc)
        return FAIL(f"Inbox খুলতে পারিনি: {exc}")

    matched = _find_collection_email(
        items, buyer, collection_code,
        max_search=settings.int("outlook_max_search", 200),
    )

    if matched is None:
        memory.log_command(str(params), "find_collection_po", False, params,
                           "email not found")
        return FAIL(
            f"{buyer.name} collection {coll_encoded} ({collection_code}) "
            f"এর কোনো email পাওয়া যায়নি।"
        )

    save_dir = os.path.join(
        settings.str("attachment_root"), buyer.name, collection_code
    )
    os.makedirs(save_dir, exist_ok=True)

    saved_files, po_numbers = _save_pdf_attachments(matched, save_dir, collection_code)

    try:
        received_str = matched.ReceivedTime.strftime("%d %B %Y")
    except Exception:
        received_str = ""

    po_list_spoken = (
        f"{len(po_numbers)}টি PO পাওয়া গেছে: " + ", ".join(po_numbers)
        if po_numbers else "কোনো PO PDF পাওয়া যায়নি।"
    )

    summary = (
        f"পেয়েছি। From: {matched.SenderName}. "
        f"Received: {received_str}. {po_list_spoken}"
    )

    duration_ms = int(time.time() * 1000) - start_ms
    memory.log_workflow(
        "find_collection_po",
        {**params, "collection_code": collection_code, "pos_found": po_numbers},
        True, duration_ms,
    )
    memory.log_command(str(params), "find_collection_po", True, params)

    try:
        matched.Display()
    except Exception as e:
        log.warning("Could not display email: %s", e)

    if po_number:
        if po_number in po_numbers:
            pdf_path = os.path.join(save_dir, f"{collection_code}-{po_number}.pdf")
            if os.path.exists(pdf_path):
                _open_file(pdf_path)
                summary += f" PO {po_number} খোলা হচ্ছে।"
            else:
                summary += f" কিন্তু PO {po_number} এর PDF পাওয়া যায়নি।"
        else:
            summary += f" কিন্তু PO {po_number} এই email-এ নেই।"

    return OK(summary)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _find_collection_email(items, buyer: Buyer, coll_code: str, max_search: int = 200):
    if buyer.collection is None:
        return None
    keywords = [kw.lower() for kw in buyer.collection.subject_keywords]
    count = 0
    try:
        for item in items:
            if count >= max_search:
                break
            count += 1
            try:
                subj = (item.Subject or "").lower()
                if all(kw in subj for kw in keywords) and coll_code in subj:
                    log.info("Matched email: %s", item.Subject)
                    return item
            except Exception:
                continue
    except Exception as exc:
        log.error("Error iterating inbox: %s", exc)
    return None


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
                log.info("Saved: %s", dest)
            else:
                log.debug("Already exists: %s", dest)
            saved_files.append(dest)
            parsed = buyer_registry.parse_po_from_filename(name)
            if parsed:
                _, po_num = parsed
                po_numbers.append(po_num)
    except Exception as exc:
        log.exception("Error saving attachments: %s", exc)
    log.info("Saved %d PDFs | POs: %s", len(saved_files), po_numbers)
    return saved_files, po_numbers


def _open_file(path: str):
    try:
        os.startfile(path)
    except Exception as exc:
        log.error("Could not open file %s: %s", path, exc)


def find_latest_buyer_po() -> ExecutionResult:
    """Legacy stub — guides user to correct syntax."""
    return FAIL(
        "Please specify buyer and collection. "
        "Example: 'Find Cecil collection 10.5'"
    )
