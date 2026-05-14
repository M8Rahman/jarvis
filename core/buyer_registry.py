"""
core/buyer_registry.py
───────────────────────
Loads buyer definitions from config/buyers.yaml and provides:

  - alias resolution:  "cecil" → Buyer(name="Cecil", ...)
  - collection encoding: "10.5" / "10 point 5" → "105"
  - full collection code: year + encoded → "2026105"

This module is the ONLY place that knows about buyer-specific logic.
All other modules (intent, workflows) use it through clean methods.

Adding a new buyer: edit config/buyers.yaml only. No code changes here.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

log = logging.getLogger("jarvis.buyer_registry")


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class CollectionConfig:
    subject_keywords:   list[str]
    attachment_pattern: str
    attachment_prefix:  str = ""


@dataclass
class Buyer:
    name:       str
    aliases:    list[str]
    order_types: list[str]
    collection: CollectionConfig | None = None

    def has_order_type(self, ot: str) -> bool:
        return ot.lower() in [x.lower() for x in self.order_types]


# ── Registry ──────────────────────────────────────────────────────────────────

class BuyerRegistry:
    """
    Loads buyers from YAML once, exposes lookup methods.
    Import the singleton `buyer_registry` defined at bottom of file.
    """

    def __init__(self):
        self._buyers: list[Buyer] = []
        self._alias_map: dict[str, Buyer] = {}
        self._load()

    def _load(self):
        yaml_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "buyers.yaml"
        )
        yaml_path = os.path.normpath(yaml_path)
        try:
            import yaml
            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except FileNotFoundError:
            log.error("buyers.yaml not found at %s", yaml_path)
            return
        except Exception as exc:
            log.error("Failed to load buyers.yaml: %s", exc)
            return

        for entry in data.get("buyers", []):
            coll_raw = entry.get("collection", {})
            coll = CollectionConfig(
                subject_keywords=coll_raw.get("subject_keywords", []),
                attachment_pattern=coll_raw.get("attachment_pattern", ""),
                attachment_prefix=coll_raw.get("attachment_prefix", ""),
            ) if coll_raw else None

            buyer = Buyer(
                name=entry["name"],
                aliases=[a.lower() for a in entry.get("aliases", [])],
                order_types=entry.get("order_types", []),
                collection=coll,
            )
            self._buyers.append(buyer)
            for alias in buyer.aliases:
                self._alias_map[alias.lower()] = buyer
            # also map the canonical name
            self._alias_map[buyer.name.lower()] = buyer

        log.info("BuyerRegistry loaded %d buyer(s).", len(self._buyers))

    # ── Public API ────────────────────────────────────────────────────────

    def resolve(self, name: str) -> Buyer | None:
        """Resolve any alias / spoken name → Buyer object."""
        return self._alias_map.get(name.strip().lower())

    def all_aliases(self) -> list[str]:
        """Return every known alias (used by IntentEngine for matching)."""
        return list(self._alias_map.keys())

    def all_buyers(self) -> list[Buyer]:
        return list(self._buyers)

    # ── Collection number helpers ─────────────────────────────────────────

    @staticmethod
    def encode_collection(raw: str) -> str:
        """
        Convert a spoken collection number to the stored integer form.

        Examples:
          "10.5"         → "105"
          "10 point 5"   → "105"
          "3"            → "30"     (whole number → x10)
          "3.0"          → "30"
          "11"           → "110"
          "105"          → "105"    (already encoded, pass-through)

        Logic:
          - Replace "point"/"দশমিক" with "."
          - If decimal present: remove dot  (10.5 → 105)
          - If whole number:   multiply ×10 (10   → 100)
          - Exception: if already 3 digits and no dot, treat as encoded
        """
        raw = raw.strip().lower()
        raw = re.sub(r"\bpoint\b|\bদশমিক\b", ".", raw)
        raw = re.sub(r"\s+", "", raw)           # remove spaces

        if "." in raw:
            # e.g. "10.5" → remove dot → "105"
            parts = raw.split(".")
            integer = parts[0]
            decimal = parts[1] if len(parts) > 1 else "0"
            return integer + decimal

        # Whole number
        try:
            n = int(raw)
        except ValueError:
            log.warning("Cannot encode collection number: %r", raw)
            return raw

        # Heuristic: 3-digit numbers are likely already encoded
        if n >= 100:
            return str(n)
        return str(n * 10)

    @staticmethod
    def build_collection_code(year: int, encoded_coll: str) -> str:
        """Combine year + encoded collection → full code used in filenames/subjects."""
        return f"{year}{encoded_coll}"

    @staticmethod
    def parse_po_from_filename(filename: str) -> tuple[str, str] | None:
        """
        Extract (collection_code, po_number) from a filename like:
          "2026105-325978.pdf"  → ("2026105", "325978")
        Returns None if pattern doesn't match.
        """
        # Remove extension
        stem = os.path.splitext(filename)[0]
        m = re.match(r"^(\d{7})-(\d+)$", stem)
        if m:
            return m.group(1), m.group(2)
        return None


# ── Singleton ─────────────────────────────────────────────────────────────────
buyer_registry = BuyerRegistry()
