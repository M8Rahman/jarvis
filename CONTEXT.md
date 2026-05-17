# JARVIS — Project Context Document
### Version: Phase 1.3  |  Last updated: 2026-05-16

> **PURPOSE OF THIS FILE:**
> Give this document to Claude at the start of any new conversation.
> It contains everything needed to continue development without losing context.
> Keep it updated as the project grows.

---

## 1. WHAT THIS PROJECT IS

A fully local/offline AI desktop assistant for Windows 11.
It listens for English voice commands, confirms before acting, and automates
desktop tasks like a trained human operator.

NOT a chatbot. NOT an autonomous agent.
A deterministic automation assistant with lightweight AI support.

---

## 2. HARDWARE

| Component | Spec |
|-----------|------|
| CPU | Intel Core i3-12100 |
| GPU | Intel UHD Graphics 730 (no CUDA) |
| RAM | 8 GB DDR4 (possible upgrade to 16/32 GB later) |
| Storage | 512 GB NVMe SSD |
| OS | Windows 11 Pro |

All models and processing run on CPU only. No GPU acceleration.

---

## 3. CORE DESIGN PHILOSOPHY

- Deterministic automation first. AI reasoning second.
- Human confirmation before every action. No autonomous execution.
- Offline-first. No cloud APIs ever.
- Low RAM. Lightweight. Modular.
- Incremental progress. One reliable workflow before adding new ones.
- Never overengineer. No agent frameworks. No LangChain. No CrewAI.
- English only. No Bangla in code, comments, prompts, or responses.

---

## 4. PROJECT FILE STRUCTURE

```
E:/Projects/JARVIS/             ← runtime data (logs, attachments, memory)
  attachments/
    Cecil/
      2026102/                  ← collection_code folders
        2026102-325978.pdf
  memory/
    jarvis_memory.db            ← SQLite memory
  logs/
    jarvis.log                  ← rotating log (5MB x 3)
    actions.log                 ← audit log

[project source root]/
  main.py
  requirements.txt
  config/
    jarvis.yaml                 ← user config (edit this)
    buyers.yaml                 ← buyer definitions (edit this)
    settings.py                 ← config loader singleton
  core/
    listener.py                 ← mic → faster-whisper → text
    intent.py                   ← text → Action (rule-based + synonyms)
    executor.py                 ← Action → runs workflow
    tts.py                      ← pyttsx3 offline TTS (dedicated thread)
    safety.py                   ← emergency stop + audit log
    state.py                    ← shared mutable state
    memory.py                   ← SQLite memory
    buyer_registry.py           ← loads buyers.yaml, resolves aliases, encodes collections
  workflows/
    erp_workflows.py            ← ERP keyboard/mouse automation (stubs)
    outlook_workflows.py        ← Outlook COM + intelligent subject scoring
    browser_workflows.py        ← Google search
  tools/
    record_workflow.py          ← records keyboard/mouse for ERP workflow capture
```

---

## 5. TECHNOLOGY STACK

| Purpose | Tool | Notes |
|---------|------|-------|
| Speech-to-text | faster-whisper (base model) | Offline, English only |
| Text-to-speech | pyttsx3 (Windows SAPI5) | Offline, English only |
| Intent matching | Rule-based + normalisation | No LLM in Phase 1 |
| Keyboard/mouse | pyautogui | FAILSAFE=True always |
| Window focus | pygetwindow | |
| Outlook | win32com (pywin32) | COM model, not UI clicking |
| Config | PyYAML | jarvis.yaml + buyers.yaml |
| Memory | SQLite (built-in) | No ORM, plain SQL |
| Hotkeys | keyboard library | Global, works system-wide |

Future (RAM >= 16 GB): Replace rule-based intent with Ollama phi3-mini

---

## 6. HOTKEYS

| Key | Action |
|-----|--------|
| Ctrl+Alt | Start listening (configurable in jarvis.yaml) |
| Ctrl+Shift+X | Emergency stop |
| Ctrl+C | Quit JARVIS |

Configurable in jarvis.yaml:
  listen_hotkey: "ctrl+alt"
  stop_hotkey:   "ctrl+shift+x"

---

## 7. BUYER SYSTEM — CRITICAL DOMAIN KNOWLEDGE

### Collection number encoding
Voice: "collection 10.2" or "collection 10 point 2"
Stored: "102" (remove decimal dot)
Full code: year + encoded → "2026102"

| Voice says | Encoded | Full code (2026) |
|-----------|---------|-----------------|
| collection 10.2 | 102 | 2026102 |
| collection 10.5 | 105 | 2026105 |
| collection 3.0  | 30  | 202630  |
| collection 11   | 110 | 2026110 |
| collection 3    | 30  | 202630  |

Rule: decimal present → remove dot. Whole number → multiply x10. 3+ digits → pass through.

### Email subject pattern (Cecil)
"Order sheet of coll 2026102" means:
- Collection code: 2026102 (year 2026, collection 10.2)

### PDF attachment naming
"2026102-325978.pdf" means:
- Collection code: 2026102
- PO number: 325978

### Attachment save path
E:/Projects/JARVIS/attachments/Cecil/2026102/2026102-325978.pdf

### Order types
- Collection — Phase 1 (implemented)
- CW — Phase 2 (not started)
- QR — Phase 2 (not started)
- NOS — Phase 2 (not started)

---

## 8. INTELLIGENT OUTLOOK SUBJECT SCORING (Phase 1.3)

The old implementation required ALL keywords to appear in the subject → missed real emails.

The new implementation scores every candidate email and picks the best match.

### Hard gate
If the collection code (e.g. "2026102") is NOT in the subject → score = 0 → excluded.
Everything below is soft scoring on top of the base 100.

### Scoring table
```
+100  collection code present                    (hard gate — REQUIRED)
+ 30  "order sheet" in subject
+ 20  "coll" or "collection" in subject
+ 15  buyer name in subject
+  5  clean original (no RE:/FW: prefix)
-  5  reply (RE:) or forward (FW:) chain
- 10  noise phrase: revised, add new quantity, correction, amendment, etc.
```

### Example results for "Find Cecil Collection 10.2" → code "2026102"
```
"Order sheet of coll 2026102"                  → score 170  ← WINNER
"Order sheet of coll 2026102 add new quantity" → score 160
"RE: Order sheet of coll 2026102"              → score 160
"FW: Some update 2026102"                      → score 115
"Unrelated email"                              → score   0  (excluded)
```

Ties broken by received date (items sorted newest-first before scanning).

### Key functions in outlook_workflows.py
- `_normalise_subject(subject)` — strip RE:/FW: chains, lowercase
- `_score_subject(subject, collection_code, buyer)` → int score
- `_find_best_collection_email(items, buyer, code, max_search)` → best email COM object

---

## 9. VOICE PIPELINE (Phase 1.2 + 1.3)

```
Hotkey pressed
    → speaker.say_and_wait("Listening.")     blocks until TTS done
    → PRE_RECORD_DELAY (0.4s)                mic opens after speaker settles
    → _record()                              captures audio + tracks speech_secs
    → Speech Gate                            < 0.5s real speech → discard, say "didn't hear"
    → Whisper transcribe (vad_filter=True)   skips silence internally
    → Hallucination filter                   "thank you" etc → None
    → intent.parse(text)                     rule-based + synonym expansion
    → confirmation (say_and_wait + keyboard) 
    → executor.run(action)
```

### Tunable constants in core/listener.py
| Constant | Default | Meaning |
|----------|---------|---------|
| SILENCE_DB | 500 | Amplitude threshold. Raise if noisy mic. |
| MIN_SPEECH_DURATION | 0.5s | Min real speech to pass gate. |
| PRE_RECORD_DELAY | 0.4s | Pause after TTS before mic opens. |
| MAX_SILENCE | 2.0s | Silence after speech → stop recording. |
| MAX_RECORD | 10.0s | Hard cap on recording time. |

---

## 10. INTENT ENGINE — COMMAND VARIATIONS SUPPORTED

All synonym expansion happens in _normalise() before matching.
Synonyms (any of these → canonical):
  find / search / locate / get / fetch / show / look for / look up /
  pull up / open / launch / start / load
  → all map to "find"

  collection / coll / col
  → all map to "collection"

So all of these match the same intent:
  "Find Cecil Collection 10.2"
  "Search Cecil coll 10.2"
  "Open order sheet Cecil 10.2"
  "Locate Cecil col 10.2"
  "Pull up Cecil collection 10.2"

---

## 11. HOW TO ADD A NEW COMMAND

1. Add IntentRule to INTENT_RULES in core/intent.py
2. Add handler to _build_handlers() in core/executor.py
3. Add handler method _h_yourname() in core/executor.py
4. Add workflow function in workflows/*.py
5. Add description to _DESCRIPTIONS in core/intent.py

No model retraining. No YAML changes (unless it's a new buyer).

---

## 12. PHASES — WHAT'S DONE AND WHAT'S NEXT

### Phase 1 (DONE)
- Voice hotkey trigger
- faster-whisper STT (offline)
- Rule-based intent engine
- Human confirmation before action
- Emergency stop
- Google search, Outlook open, ERP workflow stubs
- pyttsx3 TTS

### Phase 1.1 (DONE)
- TTS threading bug fixed (dedicated worker thread + queue)
- Buyer registry system (buyers.yaml)
- Collection number encoding logic
- Full Outlook collection PO search workflow
- PDF attachment saving (structured folders)
- SQLite memory (command_history + workflow_log)
- Text normalisation for English commands
- Rotating log files

### Phase 1.2 (DONE)
- Voice pipeline bug fixed: no more instant "cannot handle command"
- say_and_wait() used for "Listening." — mic opens after TTS finishes
- PRE_RECORD_DELAY added
- Speech gate (MIN_SPEECH_DURATION = 0.5s)
- vad_filter=True in Whisper
- Hallucination filter
- import time fix in main.py
- Debug logging throughout

### Phase 1.3 (DONE)
- ALL Bangla text removed from entire codebase (English only)
- Intelligent Outlook subject scoring system replacing simple AND-match
- _score_subject() deterministic scoring function
- _find_best_collection_email() replaces _find_collection_email()
- Subject normalisation (_normalise_subject)
- Synonym groups expanded for natural English phrasings
- buyers.yaml cleaned to English-only aliases
- All error/response messages converted to English

### Phase 2 (NEXT)
- ERP keyboard workflow implementation (use record_workflow.py first)
- CW / QR / NOS order type support
- More buyers added to buyers.yaml
- OCR screen reading for post-action verification

### Phase 3 (FUTURE — needs 16 GB RAM)
- Wake word trigger ("Hey JARVIS") via openwakeword
- Local LLM intent (Ollama phi3-mini)
- Better TTS (Coqui TTS or Edge TTS)

---

## 13. KNOWN LIMITATIONS

1. ERP workflows are stubs. Use tools/record_workflow.py to capture keystrokes,
   then fill in workflows/erp_workflows.py.

2. Collection year hardcoded to current year (datetime.now().year).
   Searching old emails from prior year will fail.
   Fix: add year extraction to intent extractor.

3. Outlook search is sequential (up to 200 emails). Large inboxes may be slow.
   Fix later: use Outlook DASL filter queries for server-side filtering.

4. pyaudio may fail to install on some systems.
   Use pre-built wheel: https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio

---

## 14. IMPORTANT CONFIG PATHS (jarvis.yaml)

```yaml
attachment_root:  E:/Projects/JARVIS/attachments
memory_db_path:   E:/Projects/JARVIS/memory/jarvis_memory.db
log_dir:          E:/Projects/JARVIS/logs
erp_window_title: "ERP"          # change to your ERP window title
erp_executable:   ""             # full path to ERP .exe
whisper_model:    base           # change to "small" if RAM allows
listen_hotkey:    "ctrl+alt"
stop_hotkey:      "ctrl+shift+x"
```

---

## 15. DEBUGGING

Set log_level: DEBUG in jarvis.yaml for full pipeline trace:

```
[MAIN]     Hotkey triggered — starting listening turn.
[MAIN]     TTS finished. Opening microphone now.
[LISTENER] Pre-recording delay 0.4s...
[LISTENER] Microphone activated — waiting for speech...
[LISTENER] Audio captured: 3.20s total, 1.84s speech
[LISTENER] Speech gate passed (1.84s). Sending to Whisper...
[LISTENER] Transcription result: 'Find Cecil Collection 10.2'
[MAIN]     Heard: 'Find Cecil Collection 10.2'
[MAIN]     Intent matched: find_collection_po | Params: {buyer: Cecil, coll_encoded: 102}
           Candidate [score=170]: 'Order sheet of coll 2026102'
           Candidate [score=160]: 'RE: Order sheet of coll 2026102'
           Best match [score=170]: 'Order sheet of coll 2026102'
```

---

## 16. HOW TO CONTINUE THIS PROJECT IN A NEW CONVERSATION

1. Give Claude this entire CONTEXT.md.
2. Share your GitHub repo link or paste relevant file contents.
3. State what you want to build next.
4. Say: "Continue from Phase X, modify incrementally."

Never ask Claude to rewrite from scratch.
