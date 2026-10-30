"""Strategie pamięci: decydują, które wcześniejsze tury trafiają do promptu.

To główna zmienna badana. Na razie dwie najprostsze strategie,
streszczenie i RAG dojdą po ustaleniu planu eksperymentów.
"""

from typing import Protocol

from app.core.schemas import NarratorResponse


class MemoryStrategy(Protocol):
    name: str

    def record(self, player_action: str, response: NarratorResponse) -> None: ...

    def history(self) -> list[dict]: ...


class FullHistory:
    """Wszystkie dotychczasowe tury dosłownie."""

    name = "full"

    def __init__(self):
        self._turns: list[tuple[str, str]] = []

    def record(self, player_action: str, response: NarratorResponse) -> None:
        self._turns.append((player_action, response.model_dump_json()))

    def _selected(self) -> list[tuple[str, str]]:
        return self._turns

    def history(self) -> list[dict]:
        messages = []
        for action, answer in self._selected():
            messages.append({"role": "user", "content": action})
            messages.append({"role": "assistant", "content": answer})
        return messages


class SlidingWindow(FullHistory):
    """Tylko ostatnie N tur dosłownie."""

    name = "window"

    def __init__(self, size: int):
        super().__init__()
        self.size = size

    def _selected(self) -> list[tuple[str, str]]:
        return self._turns[-self.size:] if self.size > 0 else []


class CachedFullHistory(FullHistory):
    """Pełna historia w układzie pod cache promptu serwera.

    Zmienne części (stan świata, lokacje) idą na koniec promptu (context.build_messages), a historia
    zapamiętuje wiadomość gracza DOKŁADNIE tak, jak została wysłana (razem ze stanem z tamtej tury).
    Dzięki temu prompt kolejnej tury to poprzedni prompt plus dopisane wiadomości. Serwer (strata-big,
    model hybrydowy) bierze z cache tylko taki przypadek, sam wspólny początek nie wystarcza.
    """

    name = "full_cached"
    records_sent_message = True


def make_memory(kind: str, window: int) -> MemoryStrategy:
    if kind == "full":
        return FullHistory()
    if kind == "full_cached":
        return CachedFullHistory()
    if kind == "window":
        return SlidingWindow(window)
    raise ValueError(f"Nieznana strategia pamięci: {kind}")
