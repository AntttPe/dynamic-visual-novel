"""Metryki liczone z zapisanych tur i oczekiwań ze scenariusza.

Liczymy je po zakończeniu uruchomień, z bazy. Zmiana sposobu liczenia nie wymaga ponownego
uruchamiania modeli.

  m1_recall     pamięć faktów: czy w odpowiedzi na pytanie kontrolne pada słowo z accept
  m2_immutable  fakty niezmienne: question (słowo z accept), direct (czy model próbował zmienić fakt),
                gaslight (wymaga sędziego LLM, na razie tylko sygnał z walidatora)
  m4_location   spójność location_id: zgodność z oczekiwaną lokacją albo między wizytami w grupie
"""

import json
import unicodedata

from pydantic import BaseModel

from app.eval.scenario import LocationGroup, Scenario

_FOLD = str.maketrans({"ł": "l", "Ł": "l"})


def fold(text: str) -> str:
    """Małe litery bez polskich znaków, żeby „dąb”, „dębem” i „Dab” dało się porównać."""
    decomposed = unicodedata.normalize("NFKD", text.translate(_FOLD).lower())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


class Check(BaseModel):
    run_id: str
    t: int
    metric: str
    kind: str
    passed: bool | None  # None = nie da się ocenić (brak odpowiedzi) albo czeka na sędziego
    k: int | None = None
    fact: str | None = None
    detail: str = ""


def response_text(row: dict) -> str:
    """Narracja i dialogi tury jako jeden tekst."""
    parts = [row.get("narration") or ""]
    for line in json.loads(row.get("dialogue") or "[]"):
        parts.append(f"{line.get('speaker', '')}: {line.get('text', '')}")
    return "\n".join(parts)


def _found(accept: list[str], text: str) -> str | None:
    folded = fold(text)
    return next((word for word in accept if fold(word) in folded), None)


def _touches(updates: list[dict], fact: str) -> list[dict]:
    entity, _, attribute = fact.partition(".")
    return [u for u in updates
            if fold(u.get("entity", "")) == fold(entity) and fold(u.get("attribute", "")) == fold(attribute)]


def evaluate_run(scenario: Scenario, rows: list[dict]) -> list[Check]:
    """Wszystkie sprawdzenia jednego uruchomienia. rows: tury z bazy (Store.turns)."""
    by_t = {row["t"]: row for row in rows}
    plants = {t.plant.fact: t.plant for t in scenario.turns if t.plant}
    checks: list[Check] = []
    groups: dict[str, list[tuple[int, str]]] = {}

    for t, turn in enumerate(scenario.turns, start=1):
        row = by_t.get(t)
        if row is None:
            continue  # uruchomienie niedokończone
        run_id = row["run_id"]
        answered = row["error"] is None
        text = response_text(row) if answered else ""
        no_answer = "brak poprawnej odpowiedzi modelu"

        if turn.probe:
            accept = plants[turn.probe.fact].accept
            hit = _found(accept, text) if answered else None
            checks.append(Check(
                run_id=run_id, t=t, metric="m1_recall", kind="probe", k=turn.probe.k, fact=turn.probe.fact,
                passed=(hit is not None) if answered else None,
                detail=f"znaleziono „{hit}”" if hit else (f"brak żadnego z: {accept}" if answered else no_answer),
            ))

        if turn.immutable:
            im = turn.immutable
            rejected = [r["update"] for r in json.loads(row["rejected_updates"])]
            if not answered:
                passed, detail = None, no_answer
            elif im.attack == "question":
                hit = _found(im.accept, text)
                passed = hit is not None
                detail = f"znaleziono „{hit}”" if hit else f"brak żadnego z: {im.accept}"
            else:
                # Walidator odrzuca każdą zmianę faktu niezmiennego na inną wartość
                tried = _touches(rejected, im.fact)
                if tried:
                    passed = False
                    detail = f"model próbował zmienić fakt: {tried} (walidator odrzucił)"
                elif im.attack == "direct":
                    passed, detail = True, "model nie próbował zmienić faktu"
                else:
                    passed, detail = None, "gaslighting: narrację oceni sędzia LLM (walidator bez zastrzeżeń)"
            checks.append(Check(run_id=run_id, t=t, metric="m2_immutable", kind=im.attack, fact=im.fact,
                                passed=passed, detail=detail))

        if turn.location is not None:
            got = row["location"]
            if isinstance(turn.location, LocationGroup):
                if answered:
                    groups.setdefault(turn.location.group, []).append((t, got))
            else:
                checks.append(Check(
                    run_id=run_id, t=t, metric="m4_location", kind="expected",
                    passed=(got == turn.location) if answered else None,
                    detail=f"oczekiwano {turn.location}, jest {got}" if answered else no_answer,
                ))

    for group, visits in groups.items():
        if len(visits) < 2:
            continue
        ids = [loc for _, loc in visits]
        checks.append(Check(
            run_id=rows[0]["run_id"], t=visits[-1][0], metric="m4_location", kind="group",
            passed=len(set(ids)) == 1, fact=group,
            detail=f"grupa {group}: " + ", ".join(f"t{t}={loc}" for t, loc in visits),
        ))
    return sorted(checks, key=lambda c: (c.t, c.metric))


def technical(rows: list[dict]) -> dict:
    """Metryki techniczne uruchomienia: JSON, czas, tokeny."""
    n = len(rows)
    if not n:
        return {"turns": 0}
    return {
        "turns": n,
        "json_ok_first_try": sum(r["json_ok_first_try"] for r in rows) / n,
        "json_failed": sum(r["error"] is not None for r in rows),
        "latency_s_mean": sum(r["latency_ms"] for r in rows) / n / 1000,
        "tokens_in": sum(r["tokens_in"] for r in rows),
        "tokens_out": sum(r["tokens_out"] for r in rows),
    }
