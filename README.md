# JARVIS — Local AI Desktop Assistant
### Phase 1.3: English-Only + Intelligent Outlook Search

Fully offline. Runs on Windows 11. English voice commands.

---

## Architecture

```
Ctrl+Alt (hotkey trigger)
       │
       ▼
┌──────────────┐  say_and_wait  ┌─────────────────────┐
│  Speaker     │ ─────────────▶ │  "Listening."        │
│  (TTS)       │                │  waits until done    │
└──────────────┘                └──────────┬──────────┘
                                           │ TTS done
                                           ▼
                              ┌─────────────────────┐
                              │  PRE_RECORD_DELAY    │  0.4s speaker decay
                              └──────────┬──────────┘
                                         │
                                         ▼
┌──────────────┐    audio     ┌─────────────────────┐
│  Microphone  │ ──────────▶  │  _record()           │
│              │              │  tracks speech_secs  │
└──────────────┘              └──────────┬──────────┘
                                         │
                              ┌──────────▼──────────┐
                              │  Speech Gate         │  < 0.5s → discard
                              └──────────┬──────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │  faster-whisper STT  │  offline, English
                              │  vad_filter=True     │
                              └──────────┬──────────┘
                                         │ text
                                         ▼
                              ┌─────────────────────┐
                              │  IntentEngine        │  rule-based matching
                              │  + normalisation     │  + synonym expansion
                              └──────────┬──────────┘
                                         │ Action
                                         ▼
                              ┌─────────────────────┐
                              │  Confirmation layer  │  "Shall I proceed?"
                              └──────────┬──────────┘
                                         │ confirmed
                                         ▼
                              ┌─────────────────────┐
                              │  ActionExecutor      │
                              └──────────┬──────────┘
                                         │
                              ┌──────────▼──────────┐
                              │  workflows/          │
                              │  erp_workflows.py    │
                              │  outlook_workflows.py│  ← intelligent scoring
                              │  browser_workflows.py│
                              └─────────────────────┘
```

---

## Setup

### 1. Prerequisites
- Python 3.11+ (Windows)
- Microphone connected
- Microsoft Outlook installed (for Outlook features)

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

> **Note on pyaudio:** If `pip install pyaudio` fails, download the wheel:
> https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio

### 3. Configure your ERP
Edit `config/jarvis.yaml`:
```yaml
erp_window_title: "Your ERP Window Title"
erp_executable:   "C:/Path/To/Your/ERP.exe"
```

### 4. Run JARVIS
```bash
python main.py
```

---

## Usage

| Action | How |
|--------|-----|
| Give a command | Press **Ctrl+Alt**, speak clearly |
| Confirm action | Say **"yes"** or press **Y** |
| Cancel action | Say **"no"** or press any key except Y |
| Emergency stop | Press **Ctrl+Shift+X** |
| Quit JARVIS | Press **Ctrl+C** in terminal |

---

## Supported Commands

| Say this... | Action |
|-------------|--------|
| "Find Cecil Collection 10.2" | Search Outlook for collection email |
| "Search Cecil coll 10.2" | Same — synonym handled |
| "Open order sheet Cecil 10.2" | Same — alternative phrasing |
| "Find collection 10.2" | Search without specifying buyer |
| "Open Outlook" | Opens Outlook |
| "PO entry" | Opens PO Entry form in ERP |
| "Open cutting report today" | Opens Cutting Report |
| "Open production report yesterday" | Opens Production Report |
| "Open ERP" | Launches ERP |
| "Search Google for [query]" | Google search |
| "Take screenshot" | Screenshot saved to logs/ |

---

## Intelligent Outlook Email Matching

When you say **"Find Cecil Collection 10.2"**, JARVIS:

1. Encodes `10.2` → `102`, builds full code `2026102`
2. Scans up to 200 Inbox emails (newest first)
3. **Scores each subject** for relevance:

| Subject | Score | Reason |
|---------|-------|--------|
| `Order sheet of coll 2026102` | ~170 | Code + "order sheet" + "coll" + clean original |
| `Order sheet of coll 2026102 add new quantity` | ~160 | Same minus noise phrase penalty |
| `RE: Order sheet of coll 2026102` | ~160 | Same minus thread prefix penalty |
| `FW: Some update 2026102` | ~115 | Code only + forward penalty |
| `Unrelated subject` | 0 | Code absent — hard filtered out |

4. Opens the **highest-scoring email** automatically
5. Saves all PDF attachments to `attachments/Cecil/2026102/`
6. Speaks: sender, date received, PO numbers found

### Scoring breakdown
```
+100  collection code in subject       (REQUIRED — hard gate)
+ 30  "order sheet" in subject
+ 20  "coll" or "collection" in subject
+ 15  buyer name in subject
+  5  clean original (no RE:/FW: prefix)
-  5  reply or forward chain
- 10  noise phrase (revised, add new quantity, correction, etc.)
```

---

## Adding a New Command

1. Add `IntentRule` to `INTENT_RULES` in `core/intent.py`
2. Add handler to `_build_handlers()` in `core/executor.py`
3. Add handler method in `core/executor.py`
4. Add workflow in `workflows/*.py`

---

## Adding a New Buyer

Edit `config/buyers.yaml` only — no code changes needed:
```yaml
- name: BuyerName
  aliases:
    - buyername
    - "buyer name"
  order_types:
    - collection
  collection:
    subject_keywords:
      - "coll"
      - "order sheet"
    attachment_pattern: "{collection_code}-{po_number}.pdf"
    attachment_prefix: ""
```

---

## Tuning Voice Sensitivity

Edit constants at the top of `core/listener.py`:

| Constant | Default | Effect |
|----------|---------|--------|
| `SILENCE_DB` | 500 | Raise if mic picks up background noise |
| `MIN_SPEECH_DURATION` | 0.5s | Raise to 0.8 if still getting false triggers |
| `PRE_RECORD_DELAY` | 0.4s | Raise if TTS audio bleeds into mic |
| `MAX_SILENCE` | 2.0s | Pause after speech before recording stops |

---

## Hardware & Model Guide

| RAM | Whisper Model | Notes |
|-----|--------------|-------|
| 8 GB | `base` | Good for clear speech |
| 16 GB | `small` | Better accuracy, noisy environments |
| 32 GB | `medium` | Best quality |

Change in `config/jarvis.yaml` → `whisper_model: small`

---

## Project Structure

```
jarvis/
├── main.py
├── requirements.txt
├── config/
│   ├── jarvis.yaml            ← edit this for your setup
│   ├── buyers.yaml            ← add buyers here (no code changes needed)
│   └── settings.py
├── core/
│   ├── listener.py            ← mic → STT (speech gate, VAD)
│   ├── intent.py              ← text → Action (rule-based + synonyms)
│   ├── executor.py            ← Action → workflow
│   ├── tts.py                 ← offline TTS (dedicated thread)
│   ├── safety.py              ← emergency stop, audit log
│   ├── state.py               ← shared state
│   ├── memory.py              ← SQLite history
│   └── buyer_registry.py      ← buyer config, collection encoding
├── workflows/
│   ├── erp_workflows.py       ← ERP automation (customize this)
│   ├── outlook_workflows.py   ← Outlook search + intelligent scoring
│   └── browser_workflows.py   ← Google search
├── tools/
│   └── record_workflow.py     ← record ERP keystrokes for replay
└── logs/
```

---

## Roadmap

- **Phase 1** — Voice → intent → confirm → action
- **Phase 1.1** — TTS threading fix, buyer registry, Outlook PO workflow
- **Phase 1.2** — Voice pipeline fix (speech gate, VAD, TTS bleed prevention)
- **Phase 1.3** — English-only, intelligent Outlook subject scoring ← current
- **Phase 2** — ERP keyboard workflows, OCR verification, more buyers
- **Phase 3** — Wake word, local LLM intent (Ollama phi3-mini, needs 16 GB RAM)

---

## Logs

| File | Contents |
|------|----------|
| `logs/jarvis.log` | All events, errors, debug info |
| `logs/actions.log` | Audit trail of every executed action |
| `logs/screenshot_*.png` | Screenshots taken by JARVIS |

Set `log_level: DEBUG` in `jarvis.yaml` to see the full pipeline trace.
