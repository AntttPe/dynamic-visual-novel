"""Context Builder: składa prompt z instrukcji, stanu świata, pamięci i akcji gracza."""

import hashlib
from pathlib import Path
from string import Template

from app.core.memory import MemoryStrategy
from app.core.state import WorldState
from app.core.world import World

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "narrator_system.md"
# Od tego nagłówka prompt zmienia się co turę (lokacja, stan). W układzie pod cache ta część idzie na koniec.
DYNAMIC_MARKER = "# Aktualna sytuacja"


def prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def prompt_version() -> str:
    """Krótki skrót treści promptu. Zapisywany przy każdej grze, żeby wyniki były powtarzalne."""
    return hashlib.sha256(prompt_template().encode()).hexdigest()[:8]


ENDING_PATH = PROMPT_PATH.parent / "narrator_ending.md"
EASY_PATH = PROMPT_PATH.parent / "narrator_easy.md"


def easy_template() -> str:
    return EASY_PATH.read_text(encoding="utf-8")


def easy_version() -> str:
    return hashlib.sha256(easy_template().encode()).hexdigest()[:8]


def ending_template() -> str:
    return ENDING_PATH.read_text(encoding="utf-8")


def ending_version() -> str:
    return hashlib.sha256(ending_template().encode()).hexdigest()[:8]


def ending_prompt(world: World, max_turns: int | None) -> str:
    """Zasady końca gry dla narratora. Bez warunków w świecie wygrana wynika z celu."""
    limit = ""
    if max_turns:
        limit = (f"- Gra ma limit {max_turns} tur. Po ostatniej turze gra kończy się przegraną, jeśli cel nie "
                 "został osiągnięty. Gdy zostaje mało tur, prowadź akcję tak, żeby rozstrzygnięcie było możliwe.")
    return Template(ending_template()).safe_substitute(
        win=world.win_condition or f"bohater osiąga cel: {world.goal}",
        lose=world.lose_condition or "bohater ginie albo osiągnięcie celu staje się niemożliwe",
        limit=limit,
    )


def build_messages(
    world: World,
    state: WorldState,
    memory: MemoryStrategy,
    player_action: str,
    *,
    current_location: str,
    known_locations: dict[str, str],
    state_in_prompt: bool,
    ending: str | None = None,
    turn_info: str | None = None,
) -> list[dict]:
    """ending: zasady końca gry (tylko gra w przeglądarce), wstawiane przed częścią zmienną promptu.
    turn_info: licznik tur, dopisywany na końcu części zmiennej, żeby nie psuć cache stałego początku."""
    if state_in_prompt:
        state_text = state.as_prompt()
        locations_text = "\n".join(f"- {loc_id}: {name}" for loc_id, name in known_locations.items())
    else:
        state_text = "(w tej konfiguracji stan świata nie jest podawany)"
        locations_text = "(w tej konfiguracji lista lokacji nie jest podawana)"
    text = Template(prompt_template()).safe_substitute(
        title=world.title,
        setting=world.setting,
        player=world.player,
        goal=world.goal,
        rules="\n".join(f"- {r}" for r in world.rules) or "(brak)",
        intro=world.intro,
        current_location=current_location,
        locations=locations_text,
        state=state_text,
    )
    if ending:
        before, marker, after = text.partition(DYNAMIC_MARKER)
        text = f"{before}{ending.strip()}\n\n{marker}{after}"
    if turn_info:
        text = f"{text.rstrip()}\n\n# Tura\n{turn_info}\n"
    if memory.name == "full_cached":
        # Stały początek (zasady, świat, historia) serwer może wziąć z cache, czyta tylko nowy koniec
        static, marker, dynamic = text.partition(DYNAMIC_MARKER)
        return [
            {"role": "system", "content": static.rstrip()},
            *memory.history(),
            {"role": "user", "content": f"{marker}{dynamic.rstrip()}\n\n# Działanie gracza\n{player_action}"},
        ]
    return [
        {"role": "system", "content": text},
        *memory.history(),
        {"role": "user", "content": player_action},
    ]
