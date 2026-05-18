"""
po_extractor/template_store.py
────────────────────────────────
Stores and retrieves PDF extraction templates.

A template is a buyer-specific layout profile that tells JARVIS:
  "For this buyer's PO PDFs, field X is found at region (x, y, w, h)
   on page N, and the OCR text can be cleaned with rule R."

Storage: JSON files in templates/ directory.
  templates/
    Cecil_collection.json
    StreetOne_collection.json
    StreetOneStudio_collection.json

Design principles:
  - Human-readable JSON: you can inspect and edit templates manually
  - One file per (buyer, order_type) pair
  - Templates store coordinate regions in normalised form (0.0–1.0)
    so they work regardless of rendering DPI or page scale
  - Each field can have multiple candidate regions (fallback zones)
  - Templates accumulate training examples over time

Template schema:
  {
    "buyer": "Cecil",
    "order_type": "collection",
    "version": 1,
    "page_size": {"width_pts": 595, "height_pts": 842},
    "extraction_method": "direct",
    "fields": {
      "po_number": {
        "label": "Purchase Order Number",
        "regions": [
          {
            "page": 0,
            "bbox_norm": [0.6, 0.05, 0.35, 0.06],
            "anchor_text": "P.O. No",
            "ocr_pattern": null,
            "trained_at": "2026-05-17T14:00:00",
            "samples_seen": 3
          }
        ],
        "post_process": "strip_prefix:P.O. No"
      },
      ...
    }
  }

bbox_norm format: [x_norm, y_norm, w_norm, h_norm]
  where all values are 0.0–1.0 relative to page dimensions.
  This makes templates DPI-independent.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

log = logging.getLogger("jarvis.template_store")

# ── Field definitions ─────────────────────────────────────────────────────────

# All extractable fields and their human-readable labels.
# This is the MASTER list — all templates use these field names.
FIELD_DEFINITIONS = {
    "buyer_name":        "Buyer Name",
    "order_type":        "Order Type (Collection/CW/QR/NOS)",
    "collection_number": "Collection Number",
    "po_number":         "Purchase Order Number",
    "style_number":      "Style Number",
    "style_description": "Style Description",
    "fob_price":         "FOB Price",
    "colors":            "Colors",
    "sizes":             "Sizes",
    "size_qty_s":        "Quantity — S",
    "size_qty_m":        "Quantity — M",
    "size_qty_l":        "Quantity — L",
    "size_qty_xl":       "Quantity — XL",
    "size_qty_xxl":      "Quantity — XXL",
    "total_quantity":    "Total Quantity",
    "delivery_date":     "Delivery Date",
    "delivery_port":     "Port of Delivery",
    "ship_mode":         "Shipping Mode",
    "currency":          "Currency",
    "lc_number":         "L/C Number",
}

FIELD_NAMES = list(FIELD_DEFINITIONS.keys())


@dataclass
class RegionRecord:
    """
    A trained region for a specific field on a specific page.
    Stores coordinates in normalised [0.0–1.0] form.
    """
    page:        int             # 0-indexed page number
    bbox_norm:   list[float]     # [x_norm, y_norm, w_norm, h_norm] all 0.0–1.0
    anchor_text: str = ""        # nearby label text (e.g. "P.O. No:")
    ocr_pattern: str = ""        # regex to further clean OCR output
    trained_at:  str = ""
    samples_seen: int = 1

    def to_pixel_bbox(self, page_width_px: int, page_height_px: int) -> tuple[int,int,int,int]:
        """Convert normalised region back to pixel coordinates."""
        xn, yn, wn, hn = self.bbox_norm
        return (
            int(xn * page_width_px),
            int(yn * page_height_px),
            int(wn * page_width_px),
            int(hn * page_height_px),
        )


@dataclass
class FieldTemplate:
    """All known regions for a specific field."""
    field_name:  str
    label:       str
    regions:     list[RegionRecord] = field(default_factory=list)
    post_process: str = ""  # e.g. "strip_prefix:P.O. No" | "regex:(\d+)"

    def best_region(self, page: int = 0) -> Optional[RegionRecord]:
        """Return the most-trained region for the given page."""
        candidates = [r for r in self.regions if r.page == page]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.samples_seen)

    def add_or_update_region(self, region: RegionRecord):
        """Add a new region or increment samples_seen if similar one exists."""
        for existing in self.regions:
            if existing.page == region.page and self._boxes_overlap(existing.bbox_norm, region.bbox_norm):
                existing.samples_seen += 1
                existing.trained_at = region.trained_at
                # Exponential moving average of bbox position
                alpha = 0.3
                existing.bbox_norm = [
                    (1 - alpha) * e + alpha * n
                    for e, n in zip(existing.bbox_norm, region.bbox_norm)
                ]
                return
        self.regions.append(region)

    @staticmethod
    def _boxes_overlap(b1: list[float], b2: list[float], threshold: float = 0.05) -> bool:
        """Return True if boxes are close enough to be the same region."""
        return all(abs(a - b) < threshold for a, b in zip(b1, b2))


@dataclass
class Template:
    """Complete extraction template for one (buyer, order_type) combination."""
    buyer:      str
    order_type: str
    version:    int = 1
    page_size:  dict = field(default_factory=lambda: {"width_pts": 595, "height_pts": 842})
    extraction_method: str = "direct"  # "direct" | "tesseract"
    fields:     dict = field(default_factory=dict)  # field_name -> FieldTemplate
    notes:      str = ""

    def get_field(self, field_name: str) -> Optional[FieldTemplate]:
        return self.fields.get(field_name)

    def set_region(self, field_name: str, region: RegionRecord):
        """Add or update a trained region for a field."""
        if field_name not in self.fields:
            self.fields[field_name] = FieldTemplate(
                field_name=field_name,
                label=FIELD_DEFINITIONS.get(field_name, field_name),
            )
        self.fields[field_name].add_or_update_region(region)

    def trained_fields(self) -> list[str]:
        """Return list of field names that have at least one trained region."""
        return [k for k, v in self.fields.items() if v.regions]

    def completion_pct(self) -> float:
        """What fraction of all known fields have been trained."""
        if not FIELD_NAMES:
            return 0.0
        return len(self.trained_fields()) / len(FIELD_NAMES) * 100


# ── Template Store ────────────────────────────────────────────────────────────

class TemplateStore:
    """
    Loads and saves templates from the templates/ directory.

    One JSON file per (buyer, order_type) pair.
    File naming: {Buyer}_{order_type}.json  (spaces replaced with underscores)
    """

    def __init__(self, templates_dir: str):
        self._dir = templates_dir
        os.makedirs(templates_dir, exist_ok=True)
        self._cache: dict[str, Template] = {}
        log.info("TemplateStore initialised at %s", templates_dir)

    def _key(self, buyer: str, order_type: str) -> str:
        return f"{buyer}_{order_type}".replace(" ", "_")

    def _path(self, buyer: str, order_type: str) -> str:
        return os.path.join(self._dir, f"{self._key(buyer, order_type)}.json")

    def load(self, buyer: str, order_type: str) -> Optional[Template]:
        """Load template from disk. Returns None if not found."""
        key = self._key(buyer, order_type)
        if key in self._cache:
            return self._cache[key]

        path = self._path(buyer, order_type)
        if not os.path.exists(path):
            return None

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            template = self._deserialise(data)
            self._cache[key] = template
            log.info("Template loaded: %s/%s (%d fields trained)",
                     buyer, order_type, len(template.trained_fields()))
            return template
        except Exception as exc:
            log.error("Failed to load template %s: %s", path, exc)
            return None

    def save(self, template: Template):
        """Save template to disk."""
        path = self._path(template.buyer, template.order_type)
        try:
            data = self._serialise(template)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._cache[self._key(template.buyer, template.order_type)] = template
            log.info("Template saved: %s/%s → %s", template.buyer, template.order_type, path)
        except Exception as exc:
            log.error("Failed to save template: %s", exc)

    def get_or_create(self, buyer: str, order_type: str) -> Template:
        """Load existing template or create a blank one."""
        t = self.load(buyer, order_type)
        if t is None:
            t = Template(buyer=buyer, order_type=order_type)
            log.info("Created new blank template: %s/%s", buyer, order_type)
        return t

    def list_templates(self) -> list[tuple[str, str]]:
        """Return all (buyer, order_type) pairs with saved templates."""
        results = []
        for fname in os.listdir(self._dir):
            if fname.endswith(".json"):
                stem = fname[:-5]
                parts = stem.split("_", 1)
                if len(parts) == 2:
                    results.append((parts[0], parts[1]))
        return results

    # ── Serialisation ─────────────────────────────────────────────────────────

    def _serialise(self, t: Template) -> dict:
        data = {
            "buyer": t.buyer,
            "order_type": t.order_type,
            "version": t.version,
            "page_size": t.page_size,
            "extraction_method": t.extraction_method,
            "notes": t.notes,
            "fields": {},
        }
        for fname, ft in t.fields.items():
            data["fields"][fname] = {
                "label": ft.label,
                "post_process": ft.post_process,
                "regions": [
                    {
                        "page": r.page,
                        "bbox_norm": r.bbox_norm,
                        "anchor_text": r.anchor_text,
                        "ocr_pattern": r.ocr_pattern,
                        "trained_at": r.trained_at,
                        "samples_seen": r.samples_seen,
                    }
                    for r in ft.regions
                ],
            }
        return data

    def _deserialise(self, data: dict) -> Template:
        fields = {}
        for fname, fdata in data.get("fields", {}).items():
            regions = [
                RegionRecord(
                    page=r["page"],
                    bbox_norm=r["bbox_norm"],
                    anchor_text=r.get("anchor_text", ""),
                    ocr_pattern=r.get("ocr_pattern", ""),
                    trained_at=r.get("trained_at", ""),
                    samples_seen=r.get("samples_seen", 1),
                )
                for r in fdata.get("regions", [])
            ]
            fields[fname] = FieldTemplate(
                field_name=fname,
                label=fdata.get("label", fname),
                regions=regions,
                post_process=fdata.get("post_process", ""),
            )
        return Template(
            buyer=data["buyer"],
            order_type=data["order_type"],
            version=data.get("version", 1),
            page_size=data.get("page_size", {}),
            extraction_method=data.get("extraction_method", "direct"),
            fields=fields,
            notes=data.get("notes", ""),
        )
