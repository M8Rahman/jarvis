# JARVIS — Local AI Desktop Assistant
### Phase 1: Voice → Intent → Confirmation → Action

Fully offline. Runs on Windows 11. Supports Banglish (Bengali + English mixed commands).

---

## Architecture

```
Ctrl+Space (hotkey trigger)
       │
       ▼
┌──────────────┐    audio     ┌─────────────────────┐
│  Listener    │ ──────────▶  │  faster-whisper STT  │  (offline, CPU)
│ (microphone) │              │  Banglish → text     │
└──────────────┘              └──────────┬──────────┘
                                         │ raw text
                                         ▼
                              ┌─────────────────────┐
                              │   IntentEngine       │
                              │   rule-based match   │
                              └──────────┬──────────┘
                                         │ Action object
                                         ▼
                              ┌─────────────────────┐
                              │  Confirmation layer  │  "করবো?" → yes/no
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
| Give a command | Press **Ctrl+Space**, then speak |
| Confirm action | Say **"হ্যাঁ"** or **"yes"** or press **Y** |
| Cancel action | Say **"না"** or **"no"** or press any key except Y |
| Emergency stop | Press **Ctrl+Shift+X** |
| Quit JARVIS | Press **Ctrl+C** in terminal |

---

## Supported Commands (Phase 1)

| Say this... | Action |
|-------------|--------|
| "PO entry করো" | Opens PO Entry form in ERP |
| "গতকালের cutting report খুলো" | Opens Cutting Report (yesterday) |
| "আজকের production report" | Opens Production Report (today) |
| "ERP খুলো" | Launches ERP application |
| "Outlook খুলো" | Opens Outlook |
| "Outlook থেকে latest buyer PO বের করো" | Finds latest PO email in inbox |
| "Google এ [query] search করো" | Opens Google search in browser |
| "Screenshot নাও" | Takes a screenshot → saved in logs/ |

---

## Adding a New Command

1. **Add intent rule** in `core/intent.py` → `INTENT_RULES` list:
```python
IntentRule(
    keywords=["your keyword", "আপনার keyword"],
    name="my_new_action",
    priority=7,
),
```

2. **Add handler** in `core/executor.py` → `_build_handlers()` dict:
```python
"my_new_action": self._h_my_new_action,
```

3. **Add handler method** in `core/executor.py`:
```python
def _h_my_new_action(self, action: Action) -> ExecutionResult:
    from workflows.erp_workflows import my_new_workflow
    return my_new_workflow()
```

4. **Add workflow** in `workflows/erp_workflows.py`:
```python
def my_new_workflow() -> ExecutionResult:
    if not _focus_erp():
        return FAIL("ERP not found.")
    # your pyautogui steps here
    return OK("Done.")
```

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

- **Phase 1** (current): Voice → intent → confirm → keyboard/mouse action
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
