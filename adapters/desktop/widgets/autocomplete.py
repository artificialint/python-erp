"""QCompleter helper — case-insensitive, substring match."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCompleter


def make_completer(options: list[str]) -> QCompleter:
    completer = QCompleter(options)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setFilterMode(Qt.MatchContains)
    return completer
