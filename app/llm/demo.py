"""Tryb demo: narrator na niby, żeby obejrzeć UI i przepływ danych bez żadnego modelu.

Nie opowiada prawdziwej historii. Rozpoznaje tylko nazwy lokacji w akcji gracza
i przy wzmiance o mieczu celowo próbuje zmienić fakt niezmienny, żeby pokazać walidator.
"""

import asyncio
import json
import re

from app.core.world import World
from app.llm.base import LLMResult

_CURRENT = re.compile(r"Gracz jest w lokacji: (\S+)")


class DemoLLM:
    model = "demo"

    def __init__(self, world: World, delay_s: float = 0.6):
        self.world = world
        self.delay_s = delay_s

    async def complete(self, messages: list[dict], **_) -> LLMResult:
        action = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        found = _CURRENT.search(messages[0]["content"])
        location_id = found.group(1) if found else self.world.start_location
        lowered = action.lower()
        for loc in self.world.locations:
            if any(alias in lowered for alias in loc.aliases):
                location_id = loc.id
        loc = self.world.location(location_id)

        narration = f"(Tryb demo, bez modelu.) Robisz to, co zamierzałeś: „{action}”."
        updates = []
        if "miecz" in lowered:
            narration += " Demo celowo próbuje zmienić materiał miecza na złoty, żeby pokazać walidator stanu."
            updates.append({"entity": "miecz", "attribute": "materiał", "value": "złoty"})
        dialogue = []
        if location_id == "tavern":
            dialogue.append({"speaker": "Borwin", "text": "Czego sobie życzysz, wędrowcze?"})

        text = json.dumps({
            "narration": narration,
            "dialogue": dialogue,
            "scene": {"location_id": location_id,
                      "description": loc.description if loc else "nieznane miejsce"},
            "state_updates": updates,
            "characters_present": [d["speaker"] for d in dialogue],
        }, ensure_ascii=False)
        await asyncio.sleep(self.delay_s)
        tokens_in = sum(len(m["content"]) for m in messages) // 4
        return LLMResult(text=text, tokens_in=tokens_in, tokens_out=len(text) // 4,
                         latency_ms=self.delay_s * 1000)
