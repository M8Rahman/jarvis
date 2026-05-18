# JARVIS — Local AI Desktop Assistant
### Phase 2.0: PO PDF Extraction + Bug Fixes

Fully offline. Runs on Windows 11. English voice commands.

---

## What's New in Phase 2.0

### Bug Fixes
| Bug | Symptom | Fix |
|-----|---------|-----|
| Collection encoding | "10.2" → `100` instead of `102` | Removed `.` from synonym group; use raw text for numeric extraction |
| Google query corruption | "Search for Kylie Jenner" → `"find for kylie jenner"` | Extractor uses raw text with trigger-word stripping |
| "Open Outlook" not matching | Intent failed after synonym expansion | Added `"find outlook"` etc. to keyword list |

### New: PO PDF Extraction System
- Say **"Extract Cecil collection PDF"** → JARVIS extracts structured fields
- Say **"Train Cecil collection PDF"** → Opens visual training interface
- Draw boxes around PDF fields to teach JARVIS their location
- Templates saved as JSON, reused for future PDFs of the same buyer

---

## Architecture

```
Ctrl+Alt (hotkey trigger)
       │
       ▼
┌──────────────┐  say_and_wait  ┌─────────────────────┐
│  Speaker     │──────────────▶ │  "Listening."        │
│  (TTS)       │                └──────────┬──────────┘
└──────────────┘                           │
                              ┌────────────▼────────────┐
                              │  PRE_RECORD_DELAY (0.4s) │
                              └────────────┬────────────┘
                                           │
┌──────────────┐    audio     ┌────────────▼────────────┐
│  Microphone  │─────────────▶│  _record() + speech gate │
└──────────────┘              └────────────┬────────────┘
                                           │
                              ┌────────────▼────────────┐
                              │  faster-whisper STT      │
                              │  (offline, English only) │
                              └────────────┬────────────┘
                                           │ text (raw + normalised)
                              ┌────────────▼────────────┐
                              │  IntentEngine            │
                              │  (rule-based matching)   │
                              └────────────┬────────────┘
                                           │ Action
                              ┌────────────▼────────────┐
                              │  Confirmation layer      │
                              └────────────┬────────────┘
                                           │ confirmed
                              ┌────────────▼────────────┐
                              │  ActionExecutor          │
                              └────────────┬────────────┘
                     ┌─────────────────────┼──────────────────────┐
                     ▼                     ▼                      ▼
           workflows/              po_extractor/           workflows/
           erp_workflows.py        FieldExtractor          outlook_workflows.py
           (ERP automation)        TrainerUI               (Outlook PO search)
                                   (PDF extraction)
```

---

## Setup

### 1. Prerequisites
- Python 3.11+ (Windows)
- Microphone connected
- Microsoft Outlook installed
- Tesseract OCR (optional, for scanned PDFs):
  https://github.com/UB-Mannheim/tesseract/wiki

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

> **pyaudio install failure?** Download wheel:
> https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio

### 3. Configure
Edit `config/jarvis.yaml`:
```yaml
erp_window_title: "Your ERP Window Title"
erp_executable:   "C:/Path/To/Your/ERP.exe"
templates_dir:    "E:/Projects/JARVIS/templates"
```

### 4. Run
```bash
python main.py
```

---

## Usage

| Action | How |
|--------|-----|
| Give a command | Press **Ctrl+Alt**, speak clearly |
| Confirm action | Say **"yes"** or press **Y** |
| Cancel action | Say **"no"** or press any other key |
| Emergency stop | **Ctrl+Shift+X** |
| Quit | **Ctrl+C** in terminal |

---

## Supported Commands

### Outlook
| Say | Action |
|-----|--------|
| "Find Cecil Collection 10.2" | Search Outlook for collection email |
| "Open Outlook" | Launch/focus Outlook |

### PO PDF Extraction (Phase 2)
| Say | Action |
|-----|--------|
| "Train Cecil collection PDF" | Open visual training interface |
| "Extract Cecil collection PDF" | Extract fields from latest downloaded PDF |
| "Read PO PDF" | Same — synonym handled |

### ERP (stubs — customize `erp_workflows.py`)
| Say | Action |
|-----|--------|
| "PO entry" | Open PO Entry form |
| "Open cutting report today" | Open Cutting Report |
| "Open production report yesterday" | Open Production Report |
| "Open ERP" | Launch ERP |

### Utility
| Say | Action |
|-----|--------|
| "Search Google for [query]" | Google search |
| "Take screenshot" | Screenshot saved to logs/ |

---

## PDF Template Training Workflow

1. Say **"Train Cecil collection PDF"** (or open trainer directly: `python -m po_extractor.trainer_ui`)
2. Select buyer name and order type in the left panel
3. Click **Open PDF…** and choose a PO PDF
4. JARVIS prompts: *"Draw box around: Purchase Order Number"*
5. Drag a rectangle on the PDF around that field
6. JARVIS shows OCR result at the bottom — press **Enter** to confirm
7. Continue field-by-field (or skip with **Next Field** button)
8. Click **Save Template** when done
9. Future PDFs from the same buyer extract automatically

### Template storage
```
E:/Projects/JARVIS/templates/
  Cecil_collection.json      ← trained regions for each field
  StreetOne_collection.json
```

### Extraction fields (20 total)
Buyer name, Order type, Collection number, PO number, Style number,
Style description, FOB price, Colors, Sizes, Size quantities (S/M/L/XL/XXL),
Total quantity, Delivery date, Port, Ship mode, Currency, L/C number

---

## Project Structure

```
jarvis/
├── main.py
├── requirements.txt
├── query.txt                  ← deferred Outlook questions (19 items)
├── CONTEXT.md                 ← give to Claude at start of new session
├── config/
│   ├── jarvis.yaml
│   ├── buyers.yaml
│   └── settings.py
├── core/
│   ├── listener.py
│   ├── intent.py              ← BUGS FIXED Phase 2
│   ├── executor.py            ← Phase 2 handlers added
│   ├── tts.py
│   ├── safety.py
│   ├── state.py
│   ├── memory.py
│   └── buyer_registry.py
├── po_extractor/              ← NEW Phase 2
│   ├── __init__.py
│   ├── pdf_renderer.py        ← PDF → PIL Image (PyMuPDF)
│   ├── ocr_engine.py          ← direct text + Tesseract OCR
│   ├── template_store.py      ← JSON template storage
│   ├── field_extractor.py     ← applies templates to extract fields
│   └── trainer_ui.py          ← Tkinter visual training UI
├── workflows/
│   ├── erp_workflows.py
│   ├── outlook_workflows.py
│   └── browser_workflows.py
└── tools/
    └── record_workflow.py
```

---

## Hardware & Model Guide

| RAM | Whisper | PDF Extraction | Notes |
|-----|---------|----------------|-------|
| 8 GB | `base` | ✓ (direct + Tesseract) | Current — works well |
| 16 GB | `small` | ✓ + local LLM intent | Better STT accuracy |
| 32 GB | `medium` | ✓ + vision model | Near-perfect accuracy |

---

## Roadmap

- **Phase 1** → Voice → intent → confirm → action ✓
- **Phase 1.1** → TTS fix, buyer registry, Outlook PO search ✓
- **Phase 1.2** → Voice pipeline (speech gate, VAD, TTS bleed) ✓
- **Phase 1.3** → English-only, intelligent Outlook subject scoring ✓
- **Phase 2.0** → Bug fixes + PDF extraction system ✓ ← **current**
- **Phase 2.1** → ERP workflows, more buyers, real PDF testing
- **Phase 3** → Wake word, local LLM intent (needs 16 GB RAM)
