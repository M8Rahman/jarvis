"""
core/executor.py
────────────────
Receives a confirmed Action and executes it.

Phase 2.0 additions:
  - extract_po_pdf handler: extracts structured data from a PO PDF
  - train_po_template handler: opens the visual training UI
  - Both handlers are lazy-imported (no RAM cost unless used)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import pyautogui
import pygetwindow as gw

from core.intent  import Action
from core.tts     import Speaker
from core.safety  import SafetyGuard
from core.memory  import memory

log = logging.getLogger("jarvis.executor")

pyautogui.PAUSE    = 0.3
pyautogui.FAILSAFE = True


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class ExecutionResult:
    success: bool
    message: str = ""


def OK(msg: str = "Done.")    -> ExecutionResult: return ExecutionResult(True,  msg)
def FAIL(msg: str = "Error.") -> ExecutionResult: return ExecutionResult(False, msg)


# ── Executor ──────────────────────────────────────────────────────────────────

class ActionExecutor:

    def __init__(self, speaker: Speaker, safety: SafetyGuard):
        self.speaker = speaker
        self.safety  = safety
        self._build_handlers()

    def run(self, action: Action) -> ExecutionResult:
        handler = self._handlers.get(action.name)
        if not handler:
            return FAIL(f"No handler registered for action: {action.name}")
        try:
            result = handler(action)
        except pyautogui.FailSafeException:
            log.warning("PyAutoGUI failsafe triggered.")
            self.safety.engage_stop()
            result = FAIL("Failsafe triggered: mouse moved to screen corner. Stopped.")
        except Exception as exc:
            log.exception("Handler '%s' raised: %s", action.name, exc)
            result = FAIL(str(exc))

        self.safety.log_action(action.name, action.params, result.success, result.message)
        return result

    def _build_handlers(self):
        self._handlers = {
            # ── Outlook / PO ────────────────────────────────────────────
            "find_collection_po":  self._h_find_collection_po,
            "open_outlook":        self._h_open_outlook,
            "read_latest_po":      self._h_read_latest_po,
            # ── ERP ─────────────────────────────────────────────────────
            "po_entry":            self._h_po_entry,
            "cutting_report":      self._h_cutting_report,
            "production_report":   self._h_production_report,
            "open_erp":            self._h_open_erp,
            # ── Browser ─────────────────────────────────────────────────
            "google_search":       self._h_google_search,
            # ── PO PDF extraction (Phase 2) ──────────────────────────────
            "extract_po_pdf":      self._h_extract_po_pdf,
            "train_po_template":   self._h_train_po_template,
            # ── Utility ─────────────────────────────────────────────────
            "take_screenshot":     self._h_take_screenshot,
        }

    def _check_stop(self) -> bool:
        return self.safety.is_stopped

    # ── Outlook handlers ──────────────────────────────────────────────────────

    def _h_find_collection_po(self, action: Action) -> ExecutionResult:
        from workflows.outlook_workflows import find_collection_po
        if self._check_stop(): return FAIL("Stopped by user.")
        if not action.params.get("buyer"):
            return FAIL(
                "Please say the buyer name with the command. "
                "Example: Find Cecil Collection 10.2"
            )
        return find_collection_po(action.params)

    def _h_open_outlook(self, action: Action) -> ExecutionResult:
        from workflows.outlook_workflows import open_outlook
        if self._check_stop(): return FAIL("Stopped by user.")
        return open_outlook()

    def _h_read_latest_po(self, action: Action) -> ExecutionResult:
        from workflows.outlook_workflows import find_latest_buyer_po
        if self._check_stop(): return FAIL("Stopped by user.")
        return find_latest_buyer_po()

    # ── ERP handlers ──────────────────────────────────────────────────────────

    def _h_po_entry(self, action: Action) -> ExecutionResult:
        from workflows.erp_workflows import open_po_entry_form
        if self._check_stop(): return FAIL("Stopped by user.")
        return open_po_entry_form()

    def _h_cutting_report(self, action: Action) -> ExecutionResult:
        from workflows.erp_workflows import open_cutting_report
        if self._check_stop(): return FAIL("Stopped by user.")
        return open_cutting_report(action.params.get("date", "today"))

    def _h_production_report(self, action: Action) -> ExecutionResult:
        from workflows.erp_workflows import open_production_report
        if self._check_stop(): return FAIL("Stopped by user.")
        return open_production_report(action.params.get("date", "today"))

    def _h_open_erp(self, action: Action) -> ExecutionResult:
        from workflows.erp_workflows import launch_erp
        if self._check_stop(): return FAIL("Stopped by user.")
        return launch_erp()

    # ── Browser handler ───────────────────────────────────────────────────────

    def _h_google_search(self, action: Action) -> ExecutionResult:
        from workflows.browser_workflows import google_search
        if self._check_stop(): return FAIL("Stopped by user.")
        query = action.params.get("query", "")
        if not query:
            return FAIL("No search query found in command.")
        return google_search(query)

    # ── PO PDF extraction handlers (Phase 2) ─────────────────────────────────

    def _h_extract_po_pdf(self, action: Action) -> ExecutionResult:
        """
        Extract structured data from a PO PDF.

        If a pdf_path is in params, use it directly.
        Otherwise, ask user to select a file via dialog.
        Requires: pymupdf installed.
        """
        if self._check_stop(): return FAIL("Stopped by user.")

        import threading
        from config.settings import settings

        pdf_path   = action.params.get("pdf_path", "")
        buyer      = action.params.get("buyer", "")
        order_type = action.params.get("order_type", "collection")

        if not pdf_path:
            # Try to find the most recently saved attachment
            attach_root = settings.str("attachment_root")
            if buyer and attach_root:
                # Walk attachments directory for this buyer
                buyer_dir = os.path.join(attach_root, buyer)
                pdf_path = self._find_latest_pdf(buyer_dir)

        if not pdf_path:
            return FAIL(
                "Please specify a PDF file path or say 'Extract Cecil collection PDF' "
                "after downloading a PO email."
            )

        if not os.path.exists(pdf_path):
            return FAIL(f"PDF not found: {pdf_path}")

        self.speaker.say(f"Extracting data from {os.path.basename(pdf_path)}. Please wait.")

        try:
            from po_extractor.template_store import TemplateStore
            from po_extractor.ocr_engine import OCREngine
            from po_extractor.field_extractor import FieldExtractor

            templates_dir = settings.str("templates_dir", "E:/Projects/JARVIS/templates")
            store    = TemplateStore(templates_dir)
            ocr      = OCREngine()
            extr     = FieldExtractor(store, ocr)

            result = extr.extract(pdf_path, buyer=buyer, order_type=order_type)

            log.info("Extraction result:\n%s", result.summary())

            fields_found = sum(1 for v in result.fields.values() if v.value)
            needs_review = result.needs_review()

            msg = (
                f"Extracted {fields_found} fields from {os.path.basename(pdf_path)}. "
                f"Method: {result.method}."
            )

            if needs_review:
                msg += f" {len(needs_review)} fields need review."

            # Show extraction result in a simple window (non-blocking)
            threading.Thread(
                target=self._show_extraction_result, args=(result,), daemon=True
            ).start()

            memory.log_workflow(
                "extract_po_pdf",
                {"pdf": pdf_path, "buyer": buyer, "fields_found": fields_found},
                True,
            )
            return OK(msg)

        except Exception as exc:
            log.exception("PDF extraction failed: %s", exc)
            return FAIL(f"Extraction failed: {exc}")

    def _h_train_po_template(self, action: Action) -> ExecutionResult:
        """Open the visual template training UI."""
        if self._check_stop(): return FAIL("Stopped by user.")

        import threading
        from config.settings import settings

        buyer      = action.params.get("buyer", "")
        order_type = action.params.get("order_type", "collection")
        pdf_path   = action.params.get("pdf_path", "")

        templates_dir = settings.str("templates_dir", "E:/Projects/JARVIS/templates")

        self.speaker.say(
            "Opening the template training window. "
            "Draw boxes around each field in the PDF."
        )

        def _launch():
            try:
                from po_extractor.trainer_ui import launch_trainer
                launch_trainer(
                    buyer=buyer,
                    order_type=order_type,
                    pdf_path=pdf_path,
                    templates_dir=templates_dir,
                )
            except Exception as exc:
                log.error("Trainer UI failed: %s", exc)

        threading.Thread(target=_launch, daemon=True).start()
        return OK("Training window opened.")

    @staticmethod
    def _find_latest_pdf(directory: str) -> str:
        """Find the most recently modified PDF in a directory tree."""
        import os
        best_path = ""
        best_mtime = 0.0
        if not os.path.isdir(directory):
            return ""
        for root, _, files in os.walk(directory):
            for fname in files:
                if fname.lower().endswith(".pdf"):
                    fpath = os.path.join(root, fname)
                    mtime = os.path.getmtime(fpath)
                    if mtime > best_mtime:
                        best_mtime = mtime
                        best_path  = fpath
        return best_path

    @staticmethod
    def _show_extraction_result(result):
        """Show extraction result in a simple Tkinter window (runs in its own thread)."""
        try:
            import tkinter as tk
            from tkinter import ttk

            root = tk.Tk()
            root.title(f"Extraction Result — {result.buyer} {result.order_type}")
            root.configure(bg="#1a1a2e")
            root.geometry("600x500")

            text = tk.Text(root, bg="#0f3460", fg="#eaeaea",
                           font=("Consolas", 10), wrap=tk.WORD,
                           borderwidth=0, padx=12, pady=12)
            text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
            text.insert(tk.END, result.summary())
            text.config(state=tk.DISABLED)

            ttk.Button(root, text="Close", command=root.destroy).pack(pady=8)
            root.mainloop()
        except Exception:
            pass

    # ── Utility handler ───────────────────────────────────────────────────────

    def _h_take_screenshot(self, action: Action) -> ExecutionResult:
        import datetime, os
        from config.settings import settings
        if self._check_stop(): return FAIL("Stopped by user.")
        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(settings.str("log_dir"), f"screenshot_{ts}.png")
        pyautogui.screenshot(path)
        log.info("Screenshot saved: %s", path)
        return OK(f"Screenshot saved to {path}")


import os
