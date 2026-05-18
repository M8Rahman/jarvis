"""
po_extractor/field_extractor.py
────────────────────────────────
Applies a trained template to extract structured field data from a PO PDF.

This is the extraction engine — it takes a Template (which knows WHERE
fields live) and an OCR result (which knows WHAT text is on the page)
and produces a structured ExtractionResult.

Two extraction modes:

MODE 1 — Template-based (preferred, after training):
  Uses the trained bbox_norm regions to crop and OCR specific areas.
  Fast, deterministic, highly accurate.
  Requires: at least one trained region per field.

MODE 2 — Heuristic fallback (before training or for new fields):
  Tries to find field values using pattern matching on full-page text.
  Less accurate but requires no training.
  Uses known PO document patterns like:
    "P.O. No: 325978" → po_number = "325978"
    "FOB: USD 12.50"  → fob_price = "12.50"

Confidence scoring:
  Each extracted value gets a confidence score (0.0–1.0).
  Template-based: confidence = min(1.0, samples_seen / 5)
  Heuristic-based: confidence = 0.4–0.7 depending on pattern strength
  This score can be shown in the UI so users know what to verify.

Post-processing rules (stored in template):
  "strip_prefix:P.O. No:"  → remove "P.O. No:" from extracted text
  "regex:(\d+)"            → apply regex, take first group
  "upper"                  → convert to uppercase
  "numeric"                → extract numeric value only
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from po_extractor.template_store import Template, FIELD_DEFINITIONS

log = logging.getLogger("jarvis.field_extractor")


# ── Result model ──────────────────────────────────────────────────────────────

@dataclass
class FieldResult:
    """Extraction result for a single field."""
    field_name:  str
    raw_text:    str           # Exactly what OCR returned
    value:       str           # After post-processing
    confidence:  float         # 0.0–1.0
    method:      str           # "template" | "heuristic" | "not_found"
    bbox_used:   Optional[list] = None  # The region that produced this result


@dataclass
class ExtractionResult:
    """Complete extraction result for one PO PDF."""
    pdf_path:    str
    buyer:       str
    order_type:  str
    page_count:  int
    extracted_at: str = ""
    fields:      dict = field(default_factory=dict)   # field_name -> FieldResult
    warnings:    list = field(default_factory=list)
    method:      str  = "unknown"   # "template" | "heuristic" | "mixed"

    def get(self, field_name: str) -> Optional[str]:
        """Return the extracted value for a field, or None."""
        r = self.fields.get(field_name)
        return r.value if r and r.value else None

    def to_dict(self) -> dict:
        """Export as plain dict for storage/display."""
        return {k: v.value for k, v in self.fields.items() if v.value}

    def summary(self) -> str:
        """Human-readable extraction summary."""
        lines = [f"=== Extraction: {self.buyer} {self.order_type} ==="]
        for fname, result in self.fields.items():
            label = FIELD_DEFINITIONS.get(fname, fname)
            if result.value:
                conf_pct = int(result.confidence * 100)
                lines.append(f"  {label}: {result.value}  [{conf_pct}% conf, {result.method}]")
            else:
                lines.append(f"  {label}: (not found)")
        return "\n".join(lines)

    def high_confidence_fields(self, threshold: float = 0.7) -> dict:
        """Return only fields with confidence above threshold."""
        return {k: v.value for k, v in self.fields.items()
                if v.value and v.confidence >= threshold}

    def needs_review(self) -> list[str]:
        """Return field names that are missing or low-confidence."""
        missing = []
        for fname in FIELD_DEFINITIONS:
            r = self.fields.get(fname)
            if not r or not r.value or r.confidence < 0.5:
                missing.append(fname)
        return missing


# ── Field Extractor ───────────────────────────────────────────────────────────

class FieldExtractor:
    """
    Extracts structured fields from PO PDF text blocks using a template.

    Usage:
        extractor = FieldExtractor(template_store, ocr_engine)
        result = extractor.extract(pdf_path, buyer="Cecil", order_type="collection")
        print(result.summary())
    """

    def __init__(self, template_store, ocr_engine):
        self._store = template_store
        self._ocr   = ocr_engine

    def extract(
        self,
        pdf_path: str,
        buyer: str,
        order_type: str,
        page_number: int = 0,
    ) -> ExtractionResult:
        """
        Main extraction entry point.

        1. Load template for (buyer, order_type)
        2. Render the page
        3. Extract text (direct or OCR)
        4. Apply template regions to each field
        5. Fall back to heuristics for unmatched fields
        6. Return ExtractionResult
        """
        from po_extractor.pdf_renderer import PDFRenderer, OCR_DPI

        result = ExtractionResult(
            pdf_path=pdf_path,
            buyer=buyer,
            order_type=order_type,
            page_count=0,
            extracted_at=datetime.now().isoformat(sep=" ", timespec="seconds"),
        )

        # ── Load template ─────────────────────────────────────────────────
        template = self._store.load(buyer, order_type)

        try:
            renderer = PDFRenderer(pdf_path)
        except Exception as exc:
            result.warnings.append(f"Cannot open PDF: {exc}")
            return result

        with renderer:
            result.page_count = renderer.page_count

            # ── Render page ───────────────────────────────────────────────
            rendered = renderer.render_page(page_number, dpi=OCR_DPI)

            # ── Extract all text blocks (smart: direct first) ─────────────
            blocks, method_used = self._ocr.extract_smart(
                pdf_path, rendered, page_number
            )
            result.method = method_used
            full_text = self._ocr.full_page_text(blocks)

            # ── Template-based extraction ─────────────────────────────────
            if template and template.trained_fields():
                template_results = self._extract_with_template(
                    template, rendered, page_number
                )
                result.fields.update(template_results)

            # ── Heuristic extraction for untrained fields ─────────────────
            heuristic_results = self._extract_heuristic(full_text, buyer, order_type)
            for fname, fresult in heuristic_results.items():
                if fname not in result.fields or not result.fields[fname].value:
                    result.fields[fname] = fresult

        # ── Finalise method label ─────────────────────────────────────────
        has_template = bool(template and template.trained_fields())
        has_heuristic = any(
            v.method == "heuristic" for v in result.fields.values()
        )
        if has_template and has_heuristic:
            result.method = "mixed"
        elif has_template:
            result.method = "template"
        elif has_heuristic:
            result.method = "heuristic"

        log.info(
            "Extraction complete: %s/%s | method=%s | %d fields found",
            buyer, order_type, result.method,
            sum(1 for v in result.fields.values() if v.value),
        )
        return result

    def _extract_with_template(
        self, template: Template, rendered, page_number: int
    ) -> dict[str, FieldResult]:
        """Extract fields using trained template regions."""
        from po_extractor.ocr_engine import BoundingBox

        results = {}
        for fname, field_tmpl in template.fields.items():
            region_rec = field_tmpl.best_region(page=page_number)
            if region_rec is None:
                continue

            # Convert normalised bbox to pixel coordinates
            px_bbox = region_rec.to_pixel_bbox(rendered.width_px, rendered.height_px)
            bbox = BoundingBox(x=px_bbox[0], y=px_bbox[1], w=px_bbox[2], h=px_bbox[3])

            # Extract text from this specific region
            blocks = self._ocr.extract_region(rendered.image, bbox)
            raw_text = " ".join(b.text for b in blocks).strip()

            # Post-process
            value = self._post_process(raw_text, field_tmpl.post_process)

            # Confidence scales with training samples (asymptotic toward 1.0)
            confidence = min(0.95, 0.5 + region_rec.samples_seen * 0.09)

            results[fname] = FieldResult(
                field_name=fname,
                raw_text=raw_text,
                value=value,
                confidence=confidence,
                method="template",
                bbox_used=region_rec.bbox_norm,
            )

        return results

    def _extract_heuristic(
        self, full_text: str, buyer: str, order_type: str
    ) -> dict[str, FieldResult]:
        """
        Pattern-based heuristic extraction for common PO fields.

        These patterns are designed for typical garment industry PO formats.
        Adjust as you discover your buyers' specific layouts.
        """
        results = {}
        text = full_text

        # ── PO Number ─────────────────────────────────────────────────────
        po_patterns = [
            r"P\.?O\.?\s*(?:No|Number|#|Num)[\s:\.]*([A-Z0-9\-]+)",
            r"Purchase\s+Order\s*(?:No|#)?[\s:\.]*([A-Z0-9\-]+)",
            r"Order\s+No[\s:\.]*([A-Z0-9\-]+)",
        ]
        for pat in po_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                results["po_number"] = FieldResult(
                    field_name="po_number",
                    raw_text=m.group(0),
                    value=m.group(1).strip(),
                    confidence=0.65,
                    method="heuristic",
                )
                break

        # ── Collection Number ─────────────────────────────────────────────
        coll_patterns = [
            r"Coll(?:ection)?[\s:\.#]*(\d{4,7})",
            r"Season[\s:\.]*(\d{4,7})",
        ]
        for pat in coll_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                results["collection_number"] = FieldResult(
                    field_name="collection_number",
                    raw_text=m.group(0),
                    value=m.group(1).strip(),
                    confidence=0.60,
                    method="heuristic",
                )
                break

        # ── Style Number ──────────────────────────────────────────────────
        style_patterns = [
            r"Style\s*(?:No|#|Number)?[\s:\.]*([A-Z0-9\-]{3,20})",
            r"Art(?:icle)?[\s:\.#]*([A-Z0-9\-]{3,20})",
        ]
        for pat in style_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                results["style_number"] = FieldResult(
                    field_name="style_number",
                    raw_text=m.group(0),
                    value=m.group(1).strip(),
                    confidence=0.60,
                    method="heuristic",
                )
                break

        # ── FOB Price ─────────────────────────────────────────────────────
        fob_patterns = [
            r"FOB[\s:\.]*(?:USD|EUR|GBP)?\s*([\d,]+\.?\d*)",
            r"Unit\s+Price[\s:\.]*(?:USD|EUR|GBP)?\s*([\d,]+\.?\d*)",
        ]
        for pat in fob_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                results["fob_price"] = FieldResult(
                    field_name="fob_price",
                    raw_text=m.group(0),
                    value=m.group(1).strip().replace(",", ""),
                    confidence=0.60,
                    method="heuristic",
                )
                break

        # ── Total Quantity ────────────────────────────────────────────────
        qty_patterns = [
            r"Total\s*(?:Qty|Quantity)[\s:\.]*(\d[\d,]*)",
            r"Grand\s+Total[\s:\.]*(\d[\d,]*)",
        ]
        for pat in qty_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                results["total_quantity"] = FieldResult(
                    field_name="total_quantity",
                    raw_text=m.group(0),
                    value=m.group(1).strip().replace(",", ""),
                    confidence=0.65,
                    method="heuristic",
                )
                break

        # ── Delivery Date ─────────────────────────────────────────────────
        date_patterns = [
            r"Delivery\s+Date[\s:\.]*(\d{1,2}[-/]\w{2,9}[-/]\d{2,4})",
            r"Ship(?:ping)?\s+Date[\s:\.]*(\d{1,2}[-/]\w{2,9}[-/]\d{2,4})",
            r"Ex(?:-?)\s*Factory[\s:\.]*(\d{1,2}[-/]\w{2,9}[-/]\d{2,4})",
        ]
        for pat in date_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                results["delivery_date"] = FieldResult(
                    field_name="delivery_date",
                    raw_text=m.group(0),
                    value=m.group(1).strip(),
                    confidence=0.60,
                    method="heuristic",
                )
                break

        # ── Currency ──────────────────────────────────────────────────────
        m = re.search(r"\b(USD|EUR|GBP|JPY|CNY)\b", text, re.IGNORECASE)
        if m:
            results["currency"] = FieldResult(
                field_name="currency",
                raw_text=m.group(0),
                value=m.group(1).upper(),
                confidence=0.70,
                method="heuristic",
            )

        # ── Buyer name ────────────────────────────────────────────────────
        # If buyer was passed in, use it directly (high confidence)
        if buyer:
            results["buyer_name"] = FieldResult(
                field_name="buyer_name",
                raw_text=buyer,
                value=buyer,
                confidence=0.90,
                method="heuristic",
            )

        # ── Order type ────────────────────────────────────────────────────
        if order_type:
            results["order_type"] = FieldResult(
                field_name="order_type",
                raw_text=order_type,
                value=order_type.upper(),
                confidence=0.90,
                method="heuristic",
            )

        return results

    @staticmethod
    def _post_process(text: str, rule: str) -> str:
        """Apply a post-processing rule to raw OCR text."""
        if not rule or not text:
            return text.strip()

        if rule.startswith("strip_prefix:"):
            prefix = rule[len("strip_prefix:"):].lower()
            lower = text.lower()
            if lower.startswith(prefix):
                text = text[len(prefix):].strip(" :.")

        elif rule.startswith("regex:"):
            pattern = rule[len("regex:"):]
            m = re.search(pattern, text)
            if m:
                text = m.group(1) if m.lastindex else m.group(0)

        elif rule == "upper":
            text = text.upper()

        elif rule == "numeric":
            m = re.search(r"[\d,]+\.?\d*", text)
            text = m.group(0).replace(",", "") if m else text

        return text.strip()
