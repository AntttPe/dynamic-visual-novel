"""Stan świata i walidator faktów niezmiennych."""

from app.core.schemas import RejectedUpdate, StateUpdate
from app.core.world import Fact


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


class WorldState:
    def __init__(self, facts: list[Fact]):
        self._facts: dict[tuple[str, str], Fact] = {
            (_norm(f.entity), _norm(f.attribute)): f.model_copy() for f in facts
        }

    def apply(self, updates: list[StateUpdate]) -> tuple[list[StateUpdate], list[RejectedUpdate]]:
        """Stosuje zmiany. Zmiana faktu niezmiennego na inną wartość jest odrzucana."""
        accepted, rejected = [], []
        for u in updates:
            key = (_norm(u.entity), _norm(u.attribute))
            fact = self._facts.get(key)
            if fact and fact.immutable:
                if _norm(u.value) != _norm(fact.value):
                    rejected.append(RejectedUpdate(
                        update=u,
                        reason=f"{fact.entity}.{fact.attribute} jest niezmienne (= {fact.value})",
                    ))
                continue
            if fact:
                fact.value = u.value
            else:
                self._facts[key] = Fact(entity=u.entity, attribute=u.attribute, value=u.value)
            accepted.append(u)
        return accepted, rejected

    def facts(self) -> list[Fact]:
        return [f.model_copy() for f in self._facts.values()]

    def as_prompt(self) -> str:
        lines = [
            f"- {f.entity}.{f.attribute} = {f.value}" + (" (NIEZMIENNE)" if f.immutable else "")
            for f in self._facts.values()
        ]
        return "\n".join(lines) or "(brak faktów)"
