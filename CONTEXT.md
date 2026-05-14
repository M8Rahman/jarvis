# JARVIS — Project Context Document
### Version: Phase 1.1  |  Last updated: 2025

> **PURPOSE OF THIS FILE:**
> Give this document to Claude at the start of any new conversation.
> It contains everything needed to continue development without losing context.
> Keep it updated as the project grows.

---

## 1. WHAT THIS PROJECT IS

A fully local/offline AI desktop assistant for Windows 11.
It runs in the background, listens for voice commands (Banglish — Bengali + English mixed),
confirms before acting, and automates desktop tasks like a trained human operator.

**NOT a chatbot. NOT an autonomous agent. A deterministic automation assistant with lightweight AI support.**

---

## 2. HARDWARE

| Component | Spec |
|-----------|------|
| CPU | Intel Core i3-12100 |
| GPU | Intel UHD Graphics 730 (no CUDA) |
| RAM | 8 GB DDR4 (possible upgrade to 16/32 GB later) |
| Storage | 512 GB NVMe SSD |
| OS | Windows 11 Pro |

**All models and processing must run on CPU only. No GPU acceleration.**

---

## 3. CORE DESIGN PHILOSOPHY

- Deterministic automation first. AI reasoning second.
- Human confirmation before every action. No autonomous execution.
- Offline-first. No cloud APIs ever.
- Low RAM. Lightweight. Modular.
- Incremental progress. One reliable workflow before adding new ones.
- Never overengineer. No agent frameworks. No LangChain. No CrewAI.

---

## 4. PROJECT FILE STRUCTURE

```
E:/Projects/JARVIS/          ← runtime data (logs, attachments, memory)
  attachments/
    Cecil/
      2026105/               ← collection_code folders
        2026105-325978.pdf
  memory/
    jarvis_memory.db         ← SQLite memory
  logs/
    jarvis.log               ← rotating log (5MB × 3)
    actions.log              ← audit log of every executed action

[project source root]/       ← wherever you cloned the repo
  main.py
  requirements.txt
  config/
    jarvis.yaml              ← user config (edit this, not code)
    buyers.yaml              ← buyer definitions (edit this, not code)
    settings.py              ← loads jarvis.yaml, provides settings singleton
  core/
    listener.py              ← microphone → faster-whisper → text
    intent.py                ← text → Action (rule-based + normalisation)
    executor.py              ← Action → runs workflow
    tts.py                   ← pyttsx3 offline TTS
    safety.py                ← emergency stop + audit log
    state.py                 ← shared mutable state (is_busy, emergency_stop)
    memory.py                ← SQLite memory (command_history, workflow_log)
    buyer_registry.py        ← loads buyers.yaml, resolves aliases, encodes collections
  workflows/
    erp_workflows.py         ← ERP keyboard/mouse automation (stubs, needs customisation)
    outlook_workflows.py     ← Outlook COM automation (working)
    browser_workflows.py     ← Google search via default browser (working)
  tools/
    record_workflow.py       ← records manual keyboard/mouse for ERP workflow capture
```

---

## 5. TECHNOLOGY STACK

| Purpose | Tool | Notes |
|---------|------|-------|
| Speech-to-text | faster-whisper (base model) | Offline, handles Banglish |
| Text-to-speech | pyttsx3 (Windows SAPI5) | Offline, no Bangla voice yet |
| Intent matching | Rule-based + normalisation | No LLM in Phase 1 |
| Keyboard/mouse | pyautogui | FAILSAFE=True always |
| Window focus | pygetwindow | |
| Outlook | win32com (pywin32) | COM model, not UI clicking |
| Config | PyYAML | jarvis.yaml + buyers.yaml |
| Memory | SQLite (built-in) | No ORM, plain SQL |
| Hotkeys | keyboard library | Global, works system-wide |

**Future (when RAM ≥ 16 GB):** Replace rule-based intent with Ollama phi3-mini or llama3.2:1b

---

## 6. HOTKEYS

| Key | Action |
|-----|--------|
| Ctrl+Shift+A | Start listening for a command (configurable in jarvis.yaml) |
| Ctrl+Shift+X | Emergency stop — halts all execution immediately |
| Ctrl+C | Quit JARVIS |

Hotkeys are configurable in jarvis.yaml:
  listen_hotkey: "ctrl+shift+a"   ← change if needed
  stop_hotkey:   "ctrl+shift+x"

WHY Ctrl+Shift+A: Does not conflict with VS Code, Windows system, or Outlook.
Ctrl+Space (VS Code autocomplete) and Alt+Space (Windows system menu) both conflict.

---

## 7. BUYER SYSTEM — CRITICAL DOMAIN KNOWLEDGE

### Collection number encoding
Buyers send orders identified by **collection numbers**.

**Encoding rule:**
- Voice: `"collection 10.5"` or `"coll 10 point 5"`
- Stored: `"105"` (remove the decimal point)
- Full code: year + encoded → `"2026105"` (year 2026, collection 10.5)

| Voice says | Encoded | Full code (2026) |
|-----------|---------|-----------------|
| collection 10.5 | 105 | 2026105 |
| collection 3.0 | 30 | 202630 |
| collection 11 | 110 | 2026110 |
| collection 3 | 30 | 202630 |

**Logic:** If decimal present → remove dot. If whole number → multiply ×10. If already 3 digits → pass through.

### Email subject pattern (Cecil)
`"Cecil Order coll. 2026105"` means:
- Buyer: Cecil
- Collection code: 2026105 (year 2026, collection 10.5)

### PDF attachment naming pattern
`"2026105-325978.pdf"` means:
- Collection code: 2026105
- PO number: 325978

### Attachment save path
`E:/Projects/JARVIS/attachments/Cecil/2026105/2026105-325978.pdf`

### Order types (per buyer, configured in buyers.yaml)
- **Collection** — Phase 1 (implemented)
- **CW** — Phase 2 (not started)
- **QR** — Phase 2 (not started)
- **NOS** — Phase 2 (not started)

---

## 8. CURRENT BUYERS (buyers.yaml)

Only Cecil is configured. More than 8 buyers exist total.
**Add buyers to `config/buyers.yaml` only — no code changes needed.**

Structure per buyer:
```yaml
- name: Cecil
  aliases: [cecil, সেসিল, Cecil]
  order_types: [collection]
  collection:
    subject_keywords: [Cecil, coll, collection]
    attachment_pattern: "{collection_code}-{po_number}.pdf"
    attachment_prefix: ""
```

---

## 9. WORKING COMMANDS (Phase 1.1)

### Collection PO search (primary workflow)
```
"Find Cecil collection 10.5"
"Cecil collection 10.5 search করো"
"Cecil coll 10.5 te PO 325978 খুঁজে দাও"
"Search Cecil collection 10 point 5 PO 325978"
```
**What JARVIS does:**
1. Resolves "Cecil" → buyer config
2. Encodes "10.5" → "105", builds "2026105"
3. Opens Outlook (launches if not running)
4. Searches Inbox (up to 200 emails) for subject containing Cecil + coll + 2026105
5. Saves all PDF attachments to E:/Projects/JARVIS/attachments/Cecil/2026105/
6. Speaks: sender, received date, list of PO numbers found
7. Opens the email in Outlook
8. If PO number specified → opens that specific PDF

### Other working commands
```
"Open Outlook"          / "Outlook খুলো"
"Google এ X search করো" / "Search X on Google"
"Screenshot নাও"
"Open ERP"              (stub — needs customisation)
"PO entry করো"          (stub — needs customisation)
"Cutting report খুলো"   (stub — needs customisation)
```

---

## 10. MEMORY SYSTEM (SQLite)

Database: `E:/Projects/JARVIS/memory/jarvis_memory.db`

**Two tables:**

`command_history` — every voice command attempted
| column | type | notes |
|--------|------|-------|
| id | INTEGER PK | |
| timestamp | TEXT | ISO format |
| raw_text | TEXT | what was heard |
| intent | TEXT | matched intent name |
| params | TEXT | JSON params |
| success | INTEGER | 0 or 1 |
| note | TEXT | failure reason etc |

`workflow_log` — every completed workflow
| column | type | notes |
|--------|------|-------|
| id | INTEGER PK | |
| timestamp | TEXT | |
| workflow | TEXT | workflow function name |
| params | TEXT | JSON params |
| success | INTEGER | |
| duration_ms | INTEGER | execution time |
| note | TEXT | |

Inspect with: **DB Browser for SQLite** (free tool)

---

## 11. INTENT ENGINE — HOW TO ADD A NEW COMMAND

1. Add `IntentRule` to `INTENT_RULES` list in `core/intent.py`
2. Add handler to `_build_handlers()` dict in `core/executor.py`
3. Add handler method `_h_yourname()` in `core/executor.py`
4. Add workflow function in appropriate `workflows/*.py` file
5. Add description to `_DESCRIPTIONS` dict in `core/intent.py`

**No model retraining. No YAML changes needed (unless it's a new buyer).**

---

## 12. PHASES — WHAT'S DONE AND WHAT'S NEXT

### Phase 1 (DONE) ✅
- Voice hotkey trigger (Ctrl+Space)
- faster-whisper STT (offline, Banglish)
- Rule-based intent engine
- Human confirmation before action
- Emergency stop (Ctrl+Shift+X)
- Google search
- Outlook open
- Basic ERP workflow stubs
- pyttsx3 TTS

### Phase 1.1 (DONE) ✅
- **English-only mode** — language="en" in Whisper (faster, no detection overhead)
- All TTS responses converted to English (Windows SAPI5 has no Bengali voice)
- TTS threading bug fixed — dedicated worker thread with queue (no more RuntimeError)
- Hotkey changed to Ctrl+Shift+A (configurable) — no VS Code conflicts
- Hotkeys configurable in jarvis.yaml (listen_hotkey / stop_hotkey)
- Audit log path fixed to use configured log_dir
- Centralised settings (jarvis.yaml + settings.py)
- Buyer registry system (buyers.yaml)
- Collection number encoding logic
- Full Outlook collection PO search workflow
- PDF attachment saving (structured folders)
- Email display in Outlook
- Specific PO PDF opening
- SQLite memory (command_history + workflow_log)
- Text normalisation for English + Banglish commands
- Rotating log files
- Audit log for every action

### Phase 2 (NEXT)
- ERP keyboard workflow implementation (use record_workflow.py to capture)
- CW / QR / NOS order type support (extend buyers.yaml + outlook_workflows.py)
- More buyers added to buyers.yaml
- OCR screen reading for verification
- Better error recovery in workflows

### Phase 3 (FUTURE — needs 16 GB RAM)
- Wake word trigger ("Hey JARVIS") via openwakeword
- Local LLM intent (Ollama phi3-mini) to replace rule-based matching
- Continuous screen observation (opt-in, only during recording mode)
- Better Bangla TTS (Coqui TTS with Bangla model)

---

## 13. KNOWN LIMITATIONS / ISSUES

1. **English only:** Windows SAPI5 has no Bengali voice. All voice commands must be in English. All JARVIS responses are English. Bengali support can be added in Phase 3 with Coqui TTS when RAM >= 16 GB.

2. **ERP workflows:** All ERP functions are stubs. They need real key sequences. Use `tools/record_workflow.py` to capture the steps, then fill in `workflows/erp_workflows.py`.

3. **Collection year hardcoded to current year:** `datetime.now().year` used. If searching for old emails from previous year, this will fail. Fix: add year extraction to intent.

4. **Outlook search is sequential:** Iterates up to 200 emails one by one. For very large inboxes, this may be slow. Fix later with Outlook's DASL filter queries.

5. **pyaudio install:** May fail on some systems. Use the pre-built wheel from https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio

---

## 14. IMPORTANT CONFIG PATHS (jarvis.yaml)

```yaml
attachment_root:  E:/Projects/JARVIS/attachments
memory_db_path:   E:/Projects/JARVIS/memory/jarvis_memory.db
log_dir:          E:/Projects/JARVIS/logs
erp_window_title: "ERP"          # ← change to your ERP's title bar text
erp_executable:   ""             # ← full path to ERP .exe
whisper_model:    base           # ← change to "small" if RAM allows
```

---

## 15. HOW TO CONTINUE THIS PROJECT IN A NEW CONVERSATION

1. Give Claude this entire document.
2. Share your GitHub repo link (or paste relevant file contents).
3. State what you want to build next.
4. Claude will read the code, understand the architecture, and continue incrementally.

**Never ask Claude to rewrite from scratch. Always say: "Continue from Phase X, modify incrementally."**
