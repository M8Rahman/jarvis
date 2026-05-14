"""
core/state.py
─────────────
Shared mutable state for the assistant.
Passed by reference to all modules so they stay in sync.
"""


class AssistantState:
    def __init__(self):
        self.is_busy:       bool = False   # True while processing a command
        self.emergency_stop: bool = False  # True = all execution halts
