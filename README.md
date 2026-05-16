# JARVIS — Local AI Desktop Assistant
### Phase 1.2: Voice Pipeline Fix — Silence Gate + TTS Bleed Prevention

Fully offline. Runs on Windows 11. Supports Banglish (Bengali + English mixed commands).

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
                              │  PRE_RECORD_DELAY    │  0.4s pause
                              │  (speaker dies down) │
                              └──────────┬──────────┘
                                         │
                                         ▼
┌──────────────┐    audio     ┌─────────────────────┐
│  Microphone  │ ──────────▶  │  _record()           │
│              │              │  tracks speech_secs  │
└──────────────┘              └──────────┬──────────┘
                                         │
                              ┌──────────▼──────────┐
                              │  Speech Gate         │  < 0.5s? → None
                              │  MIN_SPEECH_DURATION │  (no command routed)
                              └──────────┬──────────┘
                                         │ passed
                                         ▼
                              ┌─────────────────────┐
                              │  faster-whisper STT  │  (offline, CPU)
                              │  vad_filter=True     │  Banglish → text
                              └──────────┬──────────┘
                                         │
                              ┌──────────▼──────────┐
                              │  Hallucination filter│  "thank you" etc → None
                              └──────────┬──────────┘
                                         │ clean text
                                         ▼
                              ┌─────────────────────┐
                              │   IntentEngine       │
                              │   rule-based match   │
                              └──────────┬──────────┘
                                         │ Action object
                                         ▼
                              ┌─────────────────────┐
                              │  Confirmation layer  │  "Shall I proceed?"
                              └──────────┬──────────┘
                                         │ confirmed
                                         ▼
                              ┌─────────────────────┐
                              │   ActionExecutor     │
                              │   pyautogui / COM    │
                              └──────────┬──────────┘
                                         │
                              ┌──────────▼──────────┐
                              │  workflows/          │
                              │  erp_workflows.py    │
                              │  outlook_workflows.py│
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

> **Note on pyaudio:** If `pip install pyaudio` fails, download the wheel manually:
> https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio
> Then: `pip install PyAudio-0.2.14-cpXX-cpXX-win_amd64.whl`

### 3. Configure your ERP
Edit `config/jarvis.yaml`:
```yaml
erp_window_title: "Your ERP Window Title"   # part of the title bar
erp_executable:   "C:/Path/To/Your/ERP.exe" # optional auto-launch
```

### 4. Customize ERP workflows
Edit `workflows/erp_workflows.py`. Each function has a `── CUSTOMIZE THIS ──` section with clear instructions.

**To discover the right keystrokes, use the recorder:**
```bash
python tools/record_workflow.py
```
Press Ctrl+R, do the action manually in ERP, press Ctrl+R again, then Ctrl+Q to save.

### 5. Run JARVIS
```bash
python main.py
```

---

## Usage

| Action | How |
|--------|-----|
| Give a command | Press **Ctrl+Alt**, then speak |
| Confirm action | Say **"yes"** or press **Y** |
| Cancel action | Say **"no"** or press any key except Y |
| Emergency stop | Press **Ctrl+Shift+X** |
| Quit JARVIS | Press **Ctrl+C** in terminal |

---

## Supported Commands (Phase 1)

| Say this... | Action |
|-------------|--------|
| "PO entry" | Opens PO Entry form in ERP |
| "Open cutting report yesterday" | Opens Cutting Report (yesterday) |
| "Open production report today" | Opens Production Report (today) |
| "Open ERP" | Launches ERP application |
| "Open Outlook" | Opens Outlook |
| "Find Cecil collection 10.5" | Finds collection PO email in inbox |
| "Search Google for [query]" | Opens Google search in browser |
| "Take screenshot" | Takes a screenshot → saved in logs/ |

---

## Tuning Voice Sensitivity

Edit `core/listener.py` constants at the top if you get false triggers or missed commands:

| Constant | Default | Effect |
|----------|---------|--------|
| `SILENCE_DB` | `500` | Raise if mic picks up too much background noise |
| `MIN_SPEECH_DURATION` | `0.5s` | Raise to `0.8` if still getting spurious triggers |
| `PRE_RECORD_DELAY` | `0.4s` | Raise if TTS still bleeds into mic |
| `MAX_SILENCE` | `2.0s` | How long to wait after you stop speaking |

Or add them to `config/jarvis.yaml` — future versions will read these from config.

---

## Voice Pipeline — How False Triggers Are Prevented

Phase 1.2 adds three layers of protection:

1. **`say_and_wait()`** — JARVIS now waits for "Listening." to fully finish playing before opening the microphone. Previously `say()` was non-blocking, so the mic opened while the speaker was still saying "Listening." and Whisper transcribed its own output.

2. **Speech Gate (`MIN_SPEECH_DURATION`)** — After recording, JARVIS counts how many audio chunks had amplitude above the noise floor. If total real-speech time is under 0.5 seconds, the recording is silently discarded. No command is routed. No error message is spoken.

3. **VAD + Hallucination Filter** — Whisper's Voice Activity Detection (`vad_filter=True`) is now enabled so it ignores silent regions internally. Common hallucination phrases ("thank you", "you", etc.) are filtered out before the text reaches the intent engine.

---

## Adding a New Command

1. **Add intent rule** in `core/intent.py` → `INTENT_RULES` list
2. **Add handler** in `core/executor.py` → `_build_handlers()` dict
3. **Add handler method** in `core/executor.py`
4. **Add workflow** in `workflows/erp_workflows.py`

That's it. No other files need changing.

---

## Project Structure

```
jarvis/
├── main.py                    # Entry point, hotkey setup
├── requirements.txt
├── config/
│   ├── settings.py            # Config loader (singleton)
│   └── jarvis.yaml            # User-editable config ← edit this
├── core/
│   ├── listener.py            # Microphone → faster-whisper STT
│   ├── intent.py              # Text → Action (rule-based)
│   ├── executor.py            # Action → keyboard/mouse
│   ├── tts.py                 # pyttsx3 offline TTS
│   ├── safety.py              # Emergency stop, audit logging
│   └── state.py               # Shared mutable state
├── workflows/
│   ├── erp_workflows.py       # ERP navigation (customize this)
│   ├── outlook_workflows.py   # Outlook COM automation
│   └── browser_workflows.py   # Browser / Google search
├── tools/
│   └── record_workflow.py     # Record manual actions for replay
└── logs/                      # jarvis.log, actions.log, screenshots
```

---

## Hardware & Model Guide

| RAM | Recommended Whisper Model | Quality |
|-----|--------------------------|---------|
| 8 GB | `base` | Good for clear speech |
| 16 GB | `small` | Better Banglish, noisy mic |
| 32 GB | `medium` | Best quality |

Change in `config/jarvis.yaml` → `whisper_model: small`

---

## Roadmap

- **Phase 1** (done): Voice → intent → confirm → keyboard/mouse action
- **Phase 1.2** (done): Voice pipeline fix — silence gate, TTS bleed prevention, VAD
- **Phase 2**: OCR screen reading, more ERP workflows, error recovery
- **Phase 3**: Outlook email parsing + auto PO entry
- **Phase 4**: Visual screen understanding (screenshot → action)
- **Phase 5**: Wake word ("Hey JARVIS"), local LLM intent (Ollama phi3-mini)

---

## Logs

| File | Contents |
|------|----------|
| `logs/jarvis.log` | All events, errors, debug info |
| `logs/actions.log` | Audit trail of every executed action |
| `logs/screenshot_*.png` | Screenshots taken by JARVIS |
| `logs/recorded_*.txt` | Workflow recordings |

> **Tip:** Set `log_level: DEBUG` in `jarvis.yaml` to see full pipeline trace including speech gate decisions, Whisper input duration, and intent routing.
