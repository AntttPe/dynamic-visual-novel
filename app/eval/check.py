"""Sprawdza scenariusze i pokazuje, co mierzą.

Użycie:  python -m app.eval.check [id_scenariusza ...]   (bez argumentów: wszystkie)
"""

import sys

from pydantic import ValidationError

from app.eval.scenario import ScenarioError, list_scenarios, load_scenario, summary

NAMES = {"plant": "fakty podane", "probe": "pytania kontrolne (m1)", "immutable": "ataki na fakty (m2)",
         "weird": "dziwne komendy (m3)", "location": "sprawdzenia lokacji (m4)"}


def check(scenario_id: str) -> bool:
    try:
        sc = load_scenario(scenario_id)
    except (ScenarioError, ValidationError) as e:
        print(f"❌ {scenario_id}\n{e}\n")
        return False
    counts = summary(sc)
    print(f"✅ {sc.id} (wersja {sc.version}, świat {sc.world}): {counts['turns']} tur")
    for key, name in NAMES.items():
        print(f"   {name:<28} {counts.get(key, 0)}")
    ks = [f"{t.probe.fact}: k={t.probe.k}" for t in sc.turns if t.probe]
    if ks:
        print("   odległości pytań kontrolnych: " + ", ".join(ks))
    print()
    return True


if __name__ == "__main__":
    ids = sys.argv[1:] or list_scenarios()
    sys.exit(0 if all([check(i) for i in ids]) else 1)
