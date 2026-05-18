"""
po_extractor/ocr_engine.py
───────────────────────────
OCR extraction for PO PDFs.

Strategy (deterministic-first):
  TIER 1 — Direct text extraction (PyMuPDF)
    Most Cecil/Street One PDFs are digitally generated (not scanned).
    PyMuPDF extracts text directly with coordinates — zero OCR needed.
    Fast, accurate, zero CPU overhead.

  TIER 2 — Tesseract OCR (only if direct extraction fails or returns garbage)
    Used for scanned PDFs or image-based PDFs.
    Tesseract is offline, free, and adequate for clean invoice/PO layouts.
    EasyOCR is NOT used: it requires 400MB+ model download and is slow on CPU.

  Why NOT EasyOCR for this use case:
    - 400MB+ model weights: too heavy for 8GB RAM alongside Whisper
    - 3-8x slower than Tesseract on CPU for structured documents
    - Tesseract is accurate enough for printed PO text (>95% accuracy)
    - EasyOCR advantage is handwriting/non-Latin scripts — not needed here

Region extraction:
  Both tiers support extracting text from a specific pixel region.
  This is the foundation of the template training system — JARVIS
  learns to look at specific (x, y, w, h) regions for each field.

Output format:
  All methods return TextBlock objects with text + bounding box.
  This allows coordinate-aware storage in templates.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("jarvis.ocr_engine")


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class BoundingBox:
    """Pixel-space bounding box on a rendered page."""
    x: int       # left
    y: int       # top
    w: int       # width
    h: int       # height

    @property
    def x2(self) -> int: return self.x + self.w

    @property
    def y2(self) -> int: return self.y + self.h

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)

    def to_crop_box(self) -> tuple[int, int, int, int]:
        """PIL crop box format: (left, upper, right, lower)"""
        return (self.x, self.y, self.x2, self.y2)

    def expanded(self, px: int = 5) -> "BoundingBox":
        """Expand box by px on all sides (for safety margin)."""
        return BoundingBox(
            max(0, self.x - px),
            max(0, self.y - px),
            self.w + 2 * px,
            self.h + 2 * px,
        )


@dataclass
class TextBlock:
    """A piece of extracted text with its location."""
    text:       str
    bbox:       BoundingBox
    confidence: float = 1.0     # 0.0–1.0 (Tesseract provides this; direct = 1.0)
    source:     str   = "direct"   # "direct" | "tesseract"

    def is_empty(self) -> bool:
        return not self.text.strip()


# ── OCR Engine ────────────────────────────────────────────────────────────────

class OCREngine:
    """
    Unified text extraction interface.

    Usage:
        engine = OCREngine()
        # From a rendered page image:
        blocks = engine.extract_from_image(rendered_page.image)
        # From a specific region only:
        blocks = engine.extract_region(rendered_page.image, bbox)
        # Direct from PDF (preferred — no image conversion needed):
        blocks = engine.extract_direct(pdf_path, page_number=0)
    """

    def __init__(self):
        self._tesseract_available = self._check_tesseract()

    def _check_tesseract(self) -> bool:
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            log.info("Tesseract available.")
            return True
        except Exception:
            log.warning(
                "Tesseract not available. OCR will be skipped for image-based PDFs.\n"
                "Install: https://github.com/UB-Mannheim/tesseract/wiki (Windows)"
            )
            return False

    # ── TIER 1: Direct PDF text extraction ───────────────────────────────────

    def extract_direct(self, pdf_path: str, page_number: int = 0) -> list[TextBlock]:
        """
        Extract text directly from PDF using PyMuPDF (no image conversion).
        Returns blocks with precise coordinates at 72 DPI (PDF point space).

        This is the preferred method for digitally-generated PDFs.
        Typical Cecil/Street One PDFs are digital → use this first.

        Coordinates are in PDF point space (72 pts/inch).
        To convert to pixel space at N DPI: multiply by N/72.
        """
        try:
            import fitz
        except ImportError:
            log.warning("PyMuPDF not available for direct extraction.")
            return []

        try:
            doc  = fitz.open(pdf_path)
            page = doc[page_number]
            # Extract text with bounding boxes
            blocks_raw = page.get_text("blocks")
            doc.close()
        except Exception as exc:
            log.error("Direct extraction failed: %s", exc)
            return []

        results = []
        for blk in blocks_raw:
            # blk = (x0, y0, x1, y1, "text", block_no, block_type)
            if blk[6] != 0:  # skip non-text blocks (images etc)
                continue
            x0, y0, x1, y1, text = blk[0], blk[1], blk[2], blk[3], blk[4]
            text = text.strip()
            if not text:
                continue
            bbox = BoundingBox(
                x=int(x0), y=int(y0),
                w=int(x1 - x0), h=int(y1 - y0),
            )
            results.append(TextBlock(text=text, bbox=bbox, confidence=1.0, source="direct"))

        log.debug("Direct extraction: %d text blocks from page %d", len(results), page_number)
        return results

    # ── TIER 2: OCR from rendered image ──────────────────────────────────────

    def extract_from_image(self, image, dpi: int = 150) -> list[TextBlock]:
        """
        Run Tesseract OCR on a full page image.
        Returns text blocks with pixel-space coordinates.

        Args:
            image: PIL.Image.Image (full page render)
            dpi:   DPI the image was rendered at (used to report scale)
        """
        if not self._tesseract_available:
            log.warning("Tesseract not available — cannot OCR image.")
            return []

        import pytesseract
        from PIL import Image

        try:
            data = pytesseract.image_to_data(
                image,
                output_type=pytesseract.Output.DICT,
                config="--psm 6",   # Assume uniform block of text
            )
        except Exception as exc:
            log.error("Tesseract OCR failed: %s", exc)
            return []

        results = []
        n = len(data["text"])
        for i in range(n):
            text = data["text"][i].strip()
            if not text:
                continue
            conf  = int(data["conf"][i])
            if conf < 30:   # skip very low-confidence tokens
                continue
            bbox = BoundingBox(
                x=data["left"][i],
                y=data["top"][i],
                w=data["width"][i],
                h=data["height"][i],
            )
            results.append(TextBlock(
                text=text,
                bbox=bbox,
                confidence=conf / 100.0,
                source="tesseract",
            ))

        log.debug("OCR: %d text blocks extracted", len(results))
        return results

    def extract_region(self, image, bbox: BoundingBox,
                       expand_px: int = 3) -> list[TextBlock]:
        """
        Run OCR on a specific region of the image only.

        This is the core of the template extraction system.
        Once a template records bbox=(x,y,w,h) for a field like "PO Number",
        this method extracts only that region — fast and precise.

        Args:
            image:    Full page PIL Image
            bbox:     Region to extract from (pixel coordinates)
            expand_px: Safety margin to avoid cutting off text at edges
        """
        expanded = bbox.expanded(expand_px)
        crop_box = expanded.to_crop_box()

        # Clamp to image bounds
        w, h = image.size
        crop_box = (
            max(0, crop_box[0]),
            max(0, crop_box[1]),
            min(w, crop_box[2]),
            min(h, crop_box[3]),
        )

        cropped = image.crop(crop_box)

        # For small regions, upscale before OCR to improve accuracy
        cw = crop_box[2] - crop_box[0]
        ch = crop_box[3] - crop_box[1]
        if cw < 200 or ch < 30:
            scale = max(2.0, 200 / max(cw, 1))
            from PIL import Image
            cropped = cropped.resize(
                (int(cw * scale), int(ch * scale)),
                Image.LANCZOS,
            )

        blocks = self.extract_from_image(cropped)

        # Offset block coordinates back to full-page space
        for blk in blocks:
            blk.bbox.x += crop_box[0]
            blk.bbox.y += crop_box[1]

        return blocks

    # ── Smart extraction: direct first, OCR fallback ──────────────────────────

    def extract_smart(
        self,
        pdf_path: str,
        rendered_page,   # RenderedPage from pdf_renderer
        page_number: int = 0,
        min_direct_blocks: int = 5,
    ) -> tuple[list[TextBlock], str]:
        """
        Try direct extraction first. Fall back to OCR if insufficient text found.

        Returns:
            (blocks, method_used)   method_used = "direct" | "tesseract"
        """
        blocks = self.extract_direct(pdf_path, page_number)

        if len(blocks) >= min_direct_blocks:
            log.info("Smart extraction: using direct (found %d blocks)", len(blocks))
            return blocks, "direct"

        log.info(
            "Smart extraction: direct returned only %d blocks. "
            "Falling back to Tesseract OCR.", len(blocks)
        )
        blocks = self.extract_from_image(rendered_page.image, dpi=rendered_page.dpi)
        return blocks, "tesseract"

    def full_page_text(self, blocks: list[TextBlock]) -> str:
        """Join all block texts into a single string (for debugging/display)."""
        return "\n".join(b.text for b in blocks if not b.is_empty())
