# JARVIS — Project Context Document
### Version: Phase 2.0  |  Last updated: 2026-05-18

> **PURPOSE OF THIS FILE:**
> Give this document to Claude at the start of any new conversation.
> It contains everything needed to continue development without losing context.

---

## 1. WHAT THIS PROJECT IS

A fully local/offline AI desktop assistant for Windows 11.
Listens for English voice commands, confirms before acting, automates
desktop tasks like a trained human operator, and extracts structured
data from PO PDFs using a trainable template system.

NOT a chatbot. NOT an autonomous agent. NOT an LLM wrapper.
A deterministic automation assistant with targeted lightweight AI support.

---

## 2. HARDWARE

| Component | Spec |
|-----------|------|
| CPU | Intel Core i3-12100 |
| GPU | Intel UHD Graphics 730 (no CUDA) |
| RAM | 8 GB DDR4 |
| Storage | 512 GB NVMe SSD |
| OS | Windows 11 Pro |

All processing is CPU-only. No GPU acceleration.

---

## 3. CORE DESIGN PHILOSOPHY

- Deterministic automation first. AI reasoning second.
- Human confirmation before every action.
- Offline-first. No cloud APIs.
- Low RAM. Lightweight. Modular.
- Trainable, not black-box.
- English only. No Bangla in code or prompts.
- Never overengineer. No LangChain, no CrewAI, no agent frameworks.

---

## 4. PROJECT FILE STRUCTURE

```
E:/Projects/JARVIS/             ← runtime data
  attachments/
    Cecil/
      2026102/
        2026102-325978.pdf
  templates/                    ← Phase 2: PDF extraction templates
    Cecil_collection.json
    StreetOne_collection.json
  memory/
    jarvis_memory.db
  logs/
    jarvis.log
    actions.log

[source root]/
  main.py
  requirements.txt
  config/
    jarvis.yaml                 ← user config
    buyers.yaml                 ← buyer definitions
    settings.py                 ← config loader
  core/
    listener.py                 ← mic → faster-whisper → text
    intent.py                   ← text → Action (BUGS FIXED in Phase 2)
    executor.py                 ← Action → workflow (Phase 2 handlers added)
    tts.py                      ← offline TTS
    safety.py                   ← emergency stop + audit log
    state.py                    ← shared state
    memory.py                   ← SQLite memory
    buyer_registry.py           ← buyer aliases, collection encoding
  workflows/
    erp_workflows.py
    outlook_workflows.py
    browser_workflows.py
  po_extractor/                 ← Phase 2: new module
    __init__.py
    pdf_renderer.py             ← PDF → PIL Image (PyMuPDF)
    ocr_engine.py               ← text extraction (direct + Tesseract fallback)
    template_store.py           ← template JSON storage
    field_extractor.py          ← applies templates to extract fields
    trainer_ui.py               ← Tkinter visual training interface
  tools/
    record_workflow.py
  query.txt                     ← deferred Outlook/PO questions (19 items)
```

---

## 5. TECHNOLOGY STACK

| Purpose | Tool | Notes |
|---------|------|-------|
| Speech-to-text | faster-whisper (base) | Offline, English |
| Text-to-speech | pyttsx3 (SAPI5) | Offline |
| Intent matching | Rule-based | No LLM in Phase 2 |
| Keyboard/mouse | pyautogui | FAILSAFE=True |
| Window focus | pygetwindow | |
| Outlook | win32com (pywin32) | COM model |
| PDF rendering | PyMuPDF (fitz) | Fast, no dependencies |
| PDF OCR | pytesseract | Fallback for scanned PDFs |
| Image manipulation | Pillow | |
| Training UI | tkinter | Built-in, no install needed |
| Config | PyYAML | |
| Memory | SQLite | |
| Hotkeys | keyboard | |

---

## 6. BUGS FIXED IN PHASE 2.0

### BUG 1: Collection number encoding (10.2 → 100 instead of 102)
**Root cause:** `_normalise()` replaced `.` with `point` via the synonym group
`('point', 'dot', '.')`. This turned `10.2` into `10point2`. The collection
regex then captured only `10`, which encoded to `100` (×10 rule).

**Fix:** Removed `.` from the synonym group. The `_extract_collection_po()`
extractor now receives **raw text** alongside normalised text and uses raw
for numeric extraction via a separate regex that handles both `10.2` and
`10 point 2`.

**Verified:** "Find Cecil collection 10.2" → `coll_encoded="102"` ✓

### BUG 2: Google search query corrupted ("find for kylie jenner")
**Root cause:** `_extract_search_query()` worked on normalised text where
`search` → `find`. "Google search for Kylie Jenner" became "google find for
kylie jenner". The extractor found "find" as a keyword and returned everything
after it including the word "find".

**Fix:** Extractor now works on **raw text** with leading trigger pattern
stripping. "Google search for Kylie Jenner" → `query="Kylie Jenner"` ✓

### BUG 3: "Open Outlook" not matching after synonym expansion
**Root cause:** `open` → `find` in normalisation. "Open Outlook" becomes
"find outlook". The intent rule only listed "open outlook" as keyword, not
"find outlook".

**Fix:** Added `"find outlook"`, `"find mail"`, `"find inbox"` to the
`open_outlook` intent rule keywords. ✓

### BUG 4: Extractor function signature mismatch
**Root cause:** Intent rules defined extractors as `Callable[[str], dict]`
(single arg) but needed to pass both normalised and raw text.

**Fix:** All extractors now accept `(normalised: str, raw: str) -> dict`.
The `IntentEngine.parse()` passes both. ✓

---

## 7. PHASE 2 NEW FEATURE: PO PDF EXTRACTION SYSTEM

### Architecture
```
Voice: "Extract Cecil collection PDF"
          ↓
    intent: extract_po_pdf
          ↓
    executor._h_extract_po_pdf()
          ↓
    FieldExtractor.extract(pdf_path, buyer, order_type)
          ↓
    ┌─────────────────────────────────┐
    │  1. PDFRenderer → page image    │
    │  2. OCREngine.extract_smart()   │
    │     → direct text (PyMuPDF)     │
    │     → Tesseract OCR (fallback)  │
    │  3. Template-based extraction   │
    │     (if template trained)       │
    │  4. Heuristic extraction        │
    │     (pattern matching fallback) │
    │  5. ExtractionResult            │
    └─────────────────────────────────┘
          ↓
    Show result window (non-blocking Tkinter)
    Speak summary: "Extracted N fields"
```

### Training workflow
```
Voice: "Train Cecil collection PDF"
          ↓
    Opens TrainerUI (Tkinter window)
          ↓
    User opens PDF file
          ↓
    JARVIS prompts field-by-field:
    "Draw box around: Purchase Order Number"
          ↓
    User drags rectangle on PDF image
          ↓
    JARVIS OCRs region, shows result
          ↓
    User presses Enter to confirm
          ↓
    Region saved to template JSON
    (normalised coordinates 0.0-1.0)
          ↓
    Repeat until all fields trained
          ↓
    Template saved: templates/Cecil_collection.json
```

### Template storage
One JSON file per (buyer, order_type):
```
templates/
  Cecil_collection.json
  StreetOne_collection.json
  StreetOneStudio_collection.json
```

Each template stores normalised bbox coordinates [x, y, w, h] as 0.0–1.0
fractions of page dimensions. This makes templates DPI-independent —
they work regardless of rendering resolution.

### Fields tracked (20 total)
buyer_name, order_type, collection_number, po_number, style_number,
style_description, fob_price, colors, sizes, size_qty_s, size_qty_m,
size_qty_l, size_qty_xl, size_qty_xxl, total_quantity, delivery_date,
delivery_port, ship_mode, currency, lc_number

### Extraction methods
1. **Template-based** (after training): crops exact region, OCRs it.
   Confidence = 0.5 + (samples_seen × 0.09), max 0.95.
2. **Heuristic** (before training / fallback): regex patterns on full text.
   Confidence = 0.60–0.70 depending on pattern strength.
3. **Mixed**: some fields from template, some from heuristics.

### OCR strategy
- **Tier 1 — Direct** (PyMuPDF): extracts text from digital PDFs with
  exact coordinates. Zero CPU overhead. Most Cecil/Street One POs are digital.
- **Tier 2 — Tesseract**: used only for scanned/image PDFs.
  EasyOCR was NOT chosen: 400MB+ model, too slow on CPU.
- **Region-based OCR**: for template fields, only the trained region is
  OCR'd — not the whole page. Upscales small regions before OCR.

---

## 8. VOICE PIPELINE (unchanged from Phase 1.2/1.3)

Same as before. No changes in Phase 2.
See Phase 1.3 CONTEXT.md for full pipeline documentation.

---

## 9. INTENT ENGINE CHANGES (Phase 2)

Two new intent rules added:
- `extract_po_pdf`   — triggers on "extract po", "read pdf", "scan po", etc.
- `train_po_template` — triggers on "train po", "train pdf", "label pdf", etc.

All extractor functions now have signature: `(normalised: str, raw: str) -> dict`

New synonym group: `('point', 'dot')` — note `.` removed from this group.

Full keyword list for new intents:
- extract_po_pdf: ["extract po", "extract pdf", "read po", "read pdf",
                   "scan po", "process pdf", "extract purchase order"]
- train_po_template: ["train po", "train pdf", "teach pdf", "train template",
                      "train extraction", "label pdf"]

---

## 10. DEFERRED QUESTIONS

All unresolved Outlook/PO matching questions are stored in `query.txt`.
There are 19 questions across 6 sections:
- Email matching ambiguity (Q1–Q5)
- Collection number ambiguity (Q6–Q8)
- Attachment/PDF handling (Q9–Q11)
- Multi-buyer scenarios (Q12–Q14)
- Intent engine stability (Q15–Q16)
- Future Outlook features (Q17–Q19)

To address them: "Let's work through query.txt"

---

## 11. PHASES STATUS

### Phase 1 (DONE) — Basic voice + Outlook + browser
### Phase 1.1 (DONE) — TTS fix, buyer registry, Outlook PO search
### Phase 1.2 (DONE) — Voice pipeline (speech gate, VAD, TTS bleed)
### Phase 1.3 (DONE) — English-only, intelligent subject scoring
### Phase 2.0 (DONE) — Bug fixes + PDF extraction system foundation

### Phase 2.1 (NEXT)
- ERP keyboard workflow implementation
- CW / QR / NOS order type support in Outlook + PDF
- More buyers in buyers.yaml (Street One, Street One Studio)
- Test trainer UI with real Cecil PO PDFs
- Refine heuristic patterns based on actual PDF content

### Phase 3 (FUTURE — needs 16 GB RAM)
- Wake word ("Hey JARVIS") via openwakeword
- Local LLM intent (Ollama phi3-mini)
- Better TTS (Coqui TTS or Edge TTS)
- Multi-page PDF support in extractor

---

## 12. IMPORTANT CONFIG PATHS

```yaml
attachment_root:  E:/Projects/JARVIS/attachments
templates_dir:    E:/Projects/JARVIS/templates      ← NEW Phase 2
memory_db_path:   E:/Projects/JARVIS/memory/jarvis_memory.db
log_dir:          E:/Projects/JARVIS/logs
erp_window_title: "ERP"
erp_executable:   ""
whisper_model:    base
listen_hotkey:    "ctrl+alt"
stop_hotkey:      "ctrl+shift+x"
```

---

## 13. KNOWN REMAINING ISSUES

1. ERP workflows are stubs. Use tools/record_workflow.py to capture.

2. PDF trainer requires PDFs to be present locally. Voice command
   "Train Cecil collection PDF" needs a pdf_path in params — currently
   it opens the file dialog if no path is given. Future: add voice
   file path extraction or use last downloaded attachment.

3. Template training is per-page (page 0 only in Phase 2).
   Multi-page POs not yet supported.

4. The attachment PDF naming pattern discrepancy (Q9 in query.txt):
   Cecil's actual PDFs appear to be named "325978.pdf" not
   "2026102-325978.pdf" as the template specifies. This needs
   confirmation before fix.

5. Street One and Street One Studio are not yet in buyers.yaml.

---

## 14. HOW TO CONTINUE

1. Give Claude this CONTEXT.md + the relevant source files
2. State the next goal clearly
3. Say: "Continue from Phase 2.1, modify incrementally"
4. Never ask Claude to rewrite from scratch
