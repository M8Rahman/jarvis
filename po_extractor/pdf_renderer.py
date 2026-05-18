"""
po_extractor/pdf_renderer.py
─────────────────────────────
Converts PDF pages to images for OCR and visual template training.

Uses PyMuPDF (fitz) — fast, lightweight, no external dependencies.
Falls back to pdf2image (poppler) if PyMuPDF unavailable.

Design:
  - Renders at 150 DPI by default (fast OCR, low RAM)
  - 200 DPI for training (better label accuracy)
  - Returns PIL Images — compatible with OCR and Tkinter display
  - No GPU required — pure CPU rendering

RAM usage: ~20-40 MB per page at 150 DPI. Acceptable on 8 GB.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger("jarvis.pdf_renderer")

# ── Constants ─────────────────────────────────────────────────────────────────

OCR_DPI     = 150   # Fast extraction. Good enough for clean PDFs.
TRAIN_DPI   = 200   # Higher quality for template training.
MAX_DPI     = 300   # Never exceed — RAM risk on 8 GB.


@dataclass
class RenderedPage:
    """A rendered PDF page ready for OCR or display."""
    page_number: int        # 0-indexed
    image: object           # PIL.Image.Image
    width_px:  int
    height_px: int
    dpi: int

    @property
    def scale_factor(self) -> float:
        """Pixels per point (useful for coordinate mapping)."""
        return self.dpi / 72.0


# ── Renderer ──────────────────────────────────────────────────────────────────

class PDFRenderer:
    """
    Renders PDF pages to PIL Images.

    Usage:
        renderer = PDFRenderer("path/to/po.pdf")
        page = renderer.render_page(0, dpi=150)
        page.image.save("out.png")
        renderer.close()
    """

    def __init__(self, pdf_path: str):
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        self._path = pdf_path
        self._doc  = None
        self._backend = None
        self._load()

    def _load(self):
        try:
            import fitz  # PyMuPDF
            self._doc = fitz.open(self._path)
            self._backend = "pymupdf"
            log.info("PDF loaded via PyMuPDF: %s (%d pages)", self._path, len(self._doc))
        except ImportError:
            log.warning("PyMuPDF not available. Trying pdf2image (requires poppler)...")
            try:
                import pdf2image
                self._backend = "pdf2image"
                self._pdf2image_module = pdf2image
                log.info("PDF will render via pdf2image: %s", self._path)
            except ImportError:
                raise ImportError(
                    "No PDF renderer available. Install PyMuPDF:\n"
                    "  pip install pymupdf"
                )

    @property
    def page_count(self) -> int:
        if self._backend == "pymupdf":
            return len(self._doc)
        # pdf2image: count pages via pdfinfo or render all
        import subprocess
        try:
            out = subprocess.check_output(
                ["pdfinfo", self._path], stderr=subprocess.DEVNULL
            ).decode()
            for line in out.splitlines():
                if line.startswith("Pages:"):
                    return int(line.split(":")[1].strip())
        except Exception:
            pass
        return 1

    def render_page(self, page_number: int = 0, dpi: int = OCR_DPI) -> RenderedPage:
        """
        Render a single page to a PIL Image.

        Args:
            page_number: 0-indexed page number
            dpi: rendering resolution (150=fast, 200=accurate, 300=max)

        Returns:
            RenderedPage with PIL Image

        Raises:
            IndexError: if page_number >= page_count
        """
        dpi = min(dpi, MAX_DPI)

        if self._backend == "pymupdf":
            return self._render_pymupdf(page_number, dpi)
        else:
            return self._render_pdf2image(page_number, dpi)

    def render_all_pages(self, dpi: int = OCR_DPI) -> list[RenderedPage]:
        """Render all pages. Use carefully — large PDFs consume significant RAM."""
        return [self.render_page(i, dpi) for i in range(self.page_count)]

    def _render_pymupdf(self, page_number: int, dpi: int) -> RenderedPage:
        import fitz
        from PIL import Image
        import io

        if page_number >= len(self._doc):
            raise IndexError(
                f"Page {page_number} out of range (doc has {len(self._doc)} pages)"
            )

        page = self._doc[page_number]
        # PyMuPDF matrix for DPI scaling (base = 72 DPI)
        mat  = fitz.Matrix(dpi / 72, dpi / 72)
        pix  = page.get_pixmap(matrix=mat, alpha=False)
        img  = Image.open(io.BytesIO(pix.tobytes("png")))

        log.debug("Rendered page %d at %d DPI: %dx%d px", page_number, dpi, img.width, img.height)

        return RenderedPage(
            page_number=page_number,
            image=img,
            width_px=img.width,
            height_px=img.height,
            dpi=dpi,
        )

    def _render_pdf2image(self, page_number: int, dpi: int) -> RenderedPage:
        images = self._pdf2image_module.convert_from_path(
            self._path,
            dpi=dpi,
            first_page=page_number + 1,
            last_page=page_number + 1,
        )
        if not images:
            raise IndexError(f"Page {page_number} could not be rendered")
        img = images[0]
        return RenderedPage(
            page_number=page_number,
            image=img,
            width_px=img.width,
            height_px=img.height,
            dpi=dpi,
        )

    def close(self):
        if self._backend == "pymupdf" and self._doc:
            self._doc.close()
            self._doc = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
