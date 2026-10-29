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


def build_messages(
    world: World,
    state: WorldState,
    memory: MemoryStrategy,
    player_action: str,
    *,
    current_location: str,
    known_locations: dict[str, str],
    state_in_prompt: bool,
) -> list[dict]:
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
