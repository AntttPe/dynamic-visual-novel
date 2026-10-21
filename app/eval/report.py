"""Raport wyników eksperymentów w terminalu.

Użycie (w kontenerze):
  python -m app.eval.report                       # wszystkie uruchomienia main_v2
  python -m app.eval.report --details             # plus lista nieudanych sprawdzeń
  python -m app.eval.report --csv data/eval.csv   # wszystkie sprawdzenia do pliku (analiza, wykresy)
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

from app.config import settings
from app.eval.metrics import Check, evaluate_run, technical
from app.eval.scenario import load_scenario
from app.storage.db import Store


def rate(checks: list[Check]) -> str:
    judged = [c for c in checks if c.passed is not None]
    if not judged:
        return "brak danych" if not checks else f"czeka na sędziego ({len(checks)})"
    ok = sum(c.passed for c in judged)
    text = f"{ok}/{len(judged)} ({100 * ok / len(judged):.0f}%)"
    pending = len(checks) - len(judged)
    return text + (f", nieocenione: {pending}" if pending else "")


def describe(run: dict) -> str:
    state = "stan w prompcie" if run["state_in_prompt"] else "BEZ stanu"
    tag = f", tag {run['tag']}" if run["tag"] else ""
    return (f"{run['model']} | pamięć {run['history']}/{run['memory_window']} | {state} | "
            f"temp {run['temperature']}{tag}")


def main() -> None:
    p = argparse.ArgumentParser(description="Wyniki eksperymentów.")
    p.add_argument("--scenario", default="main_v2")
    p.add_argument("--tag", default=None)
    p.add_argument("--details", action="store_true", help="pokaż nieudane i nieocenione sprawdzenia")
    p.add_argument("--csv", help="zapisz wszystkie sprawdzenia do pliku CSV")
    args = p.parse_args()

    scenario = load_scenario(args.scenario)
    store = Store(Path(settings.data_dir) / "dvn.sqlite")
    runs = store.eval_runs(args.scenario, args.tag)
    if not runs:
        print(f"Brak uruchomień scenariusza {args.scenario}. Najpierw: python -m app.eval.run")
        return

    by_config: dict[str, list[dict]] = defaultdict(list)
    for run in runs:
        by_config[run["config_key"]].append(run)

    all_checks: list[tuple[dict, Check]] = []
    for key, config_runs in by_config.items():
        first = config_runs[0]
        print("=" * 100)
        print(f"Konfiguracja {key}: {describe(first)}")
        stale = {r["scenario_version"] for r in config_runs} - {scenario.version}
        if stale:
            print(f"  UWAGA: uruchomienia dla innej wersji scenariusza ({stale}), sprawdzenia mogą nie pasować")
        statuses = ", ".join(f"powt. {r['rep']}: {r['status']}" for r in config_runs)
        print(f"  Uruchomienia: {statuses}")

        checks: list[Check] = []
        rows_all: list[dict] = []
        for run in config_runs:
            rows = store.turns(run["run_id"])
            rows_all += rows
            run_checks = evaluate_run(scenario, rows)
            checks += run_checks
            all_checks += [(run, c) for c in run_checks]

        def pick(metric: str, kind: str | None = None, checks: list[Check] = checks) -> list[Check]:
            return [c for c in checks if c.metric == metric and (kind is None or c.kind == kind)]

        print(f"\n  M1 pamięć faktów          {rate(pick('m1_recall'))}")
        for k in sorted({c.k for c in pick("m1_recall")}):
            print(f"     k={k:<3} {rate([c for c in pick('m1_recall') if c.k == k])}")
        print(f"  M2 fakty niezmienne       {rate([c for c in pick('m2_immutable') if c.kind != 'gaslight'])}"
              "   (bez gaslightingu)")
        for kind, name in (("question", "pytanie o fakt"), ("direct", "próba zmiany"), ("gaslight", "gaslighting")):
            print(f"     {name:<16} {rate(pick('m2_immutable', kind))}")
        print(f"  M4 spójność lokacji       {rate(pick('m4_location'))}")
        print(f"     oczekiwana lokacja {rate(pick('m4_location', 'expected'))}")
        print(f"     ten sam id w grupie {rate(pick('m4_location', 'group'))}")
        print("  M3 dziwne komendy         czeka na sędziego LLM (kolejny krok)")

        tech = technical(rows_all)
        if tech["turns"]:
            print(f"\n  Technicznie: {tech['turns']} tur, JSON ok za 1. razem {100 * tech['json_ok_first_try']:.0f}%, "
                  f"błędne JSON: {tech['json_failed']}, średnio {tech['latency_s_mean']:.1f} s/turę, "
                  f"tokeny {tech['tokens_in']}/{tech['tokens_out']}")

        if args.details:
            bad = [c for c in checks if c.passed is not True]
            if bad:
                print("\n  Nieudane i nieocenione:")
            for c in bad:
                mark = "❌" if c.passed is False else "…"
                rep = next(r["rep"] for r in config_runs if r["run_id"] == c.run_id)
                print(f"   {mark} powt. {rep} t{c.t:<3} {c.metric:<13} {c.kind:<9} {c.detail}")
        print()

    if args.csv:
        path = Path(args.csv)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["config_key", "model", "history", "window", "state_in_prompt", "rep",
                             "run_id", "t", "metric", "kind", "fact", "k", "passed", "detail"])
            for run, c in all_checks:
                writer.writerow([run["config_key"], run["model"], run["history"], run["memory_window"],
                                 run["state_in_prompt"], run["rep"], c.run_id, c.t, c.metric, c.kind,
                                 c.fact, c.k, c.passed, c.detail])
        print(f"Zapisano {len(all_checks)} sprawdzeń do {path}")


if __name__ == "__main__":
    main()
