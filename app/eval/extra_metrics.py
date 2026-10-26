"""Dodatkowe metryki X1 do X5, liczone z zapisanych gier (bez modelu, tylko biblioteka standardowa).

Użycie (w kontenerze):
  python -m app.eval.extra_metrics --tag long50
  python -m app.eval.extra_metrics --tag long50 --csv data/eval/long50_extra.csv   # wiersz = gra
  python -m app.eval.extra_metrics --tag long50 --names 20   # losowe trafienia X3 do ręcznej oceny

  X1 zapis faktu   czy fakt z próbki M1 trafił do stanu świata (tura podania albo następna)
                   i rozbicie M1 na 2×2: zapisał/nie zapisał × pamięta/zapomniał
  X2 opis lokacji  podobieństwo scene_description: ta sama lokacja (różne wizyty) vs różne lokacje.
                   Przybliżenie leksykalne (Jaccard słów, cosinus trigramów znakowych),
                   docelowo embeddingi CLIP/tekstowe
  X3 zmyślone byty nowe nazwy własne (heurystyka: wielka litera nie na początku zdania)
                   i mówiący spoza characters_present
  X4 powtarzalność trigramy słów wspólne z poprzednią turą, distinct-2, najczęstsze 4-gramy
  X5 koszt gry     nachylenie tokens_in względem tury, suma tokenów i czasu, fakty w stanie, odrzucone zmiany

Porównanie „ze stanem minus bez stanu” liczone jest na parach gier z tym samym modelem i seedem:
McNemar (dokładny) dla wyników tak/nie, test znaków i bootstrap par dla liczb.
"""

import argparse
import csv
import json
import math
import random
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from app.config import settings
from app.core.engine import extract_json
from app.core.world import World, load_world
from app.eval.metrics import evaluate_run, fold
from app.eval.scenario import Scenario, load_scenario
from app.storage.db import Store

# --- Tekst ---


def tokens(text: str) -> list[str]:
    """Słowa po fold (małe litery, bez polskich znaków i interpunkcji)."""
    return re.findall(r"[a-z0-9]+", fold(text))


def content_words(text: str) -> set[str]:
    """Słowa dłuższe niż 3 litery (bez „i”, „na”, „się”)."""
    return {w for w in tokens(text) if len(w) > 3}


def ngrams(words: list[str], n: int) -> list[tuple[str, ...]]:
    return [tuple(words[i:i + n]) for i in range(len(words) - n + 1)]


def jaccard(a: str, b: str) -> float:
    wa, wb = content_words(a), content_words(b)
    return len(wa & wb) / len(wa | wb) if wa | wb else 0.0


def trigram_cosine(a: str, b: str) -> float:
    def grams(text: str) -> Counter:
        s = " ".join(tokens(text))
        return Counter(s[i:i + 3] for i in range(len(s) - 2))

    ga, gb = grams(a), grams(b)
    dot = sum(ga[g] * gb[g] for g in ga.keys() & gb.keys())
    norm = math.sqrt(sum(v * v for v in ga.values())) * math.sqrt(sum(v * v for v in gb.values()))
    return dot / norm if norm else 0.0


def turn_text(row: dict) -> str:
    """Narracja i wypowiedzi tury, bez imion mówiących."""
    lines = json.loads(row.get("dialogue") or "[]")
    return "\n".join([row.get("narration") or ""] + [line.get("text", "") for line in lines])


def characters_present(row: dict) -> list[str]:
    """characters_present nie ma osobnej kolumny, więc czytamy je z surowej odpowiedzi."""
    try:
        return json.loads(extract_json(row["raw_output"])).get("characters_present") or []
    except (ValueError, AttributeError):
        return []


def answered(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["error"] is None]


# --- X1: zapis faktu w stanie ---


def _fact_text(fact: dict) -> str:
    return fold(f"{fact['entity']} {fact['attribute']} {fact['value']}")


def new_facts(before: list[dict], after: list[dict]) -> list[str]:
    """Fakty dopisane albo zmienione między dwoma stanami."""
    old = {_fact_text(f) for f in before}
    return [_fact_text(f) for f in after if _fact_text(f) not in old]


def x1_writes(scenario: Scenario, world: World, rows: list[dict]) -> dict[str, dict]:
    """Dla każdego faktu z plant: czy model zapisał go w stanie w turze podania albo w następnej.

    Szukamy słowa z accept tylko w faktach dopisanych w tej turze, żeby nie liczyć przypadkowych
    trafień w starszych faktach (np. „dębowa brama” przy fakcie o dębie).
    """
    by_t = {r["t"]: r for r in rows}
    initial = [f.model_dump() for f in world.facts]

    def state(t: int) -> list[dict] | None:
        if t == 0:
            return initial
        return json.loads(by_t[t]["state_after"]) if t in by_t else None

    def written(t: int, accept: list[str]) -> bool:
        before, after = state(t - 1), state(t)
        if before is None or after is None:
            return False
        added = " | ".join(new_facts(before, after))
        return any(fold(word) in added for word in accept)

    result = {}
    for t, turn in enumerate(scenario.turns, start=1):
        if turn.plant and t in by_t:
            now = written(t, turn.plant.accept)
            later = not now and written(t + 1, turn.plant.accept)
            result[turn.plant.fact] = {"t": t, "written": now or later, "delayed": later}
    return result


def x1_breakdown(scenario: Scenario, world: World, rows: list[dict]) -> list[dict]:
    """Każde pytanie kontrolne M1 z informacją, czy fakt był zapisany w stanie."""
    writes = x1_writes(scenario, world, rows)
    out = []
    for c in evaluate_run(scenario, rows):
        if c.metric == "m1_recall" and c.passed is not None and c.fact in writes:
            out.append({"t": c.t, "fact": c.fact, "k": c.k, "written": writes[c.fact]["written"],
                        "recalled": c.passed})
    return out


# --- X2: stabilność opisu lokacji ---


def visits(rows: list[dict]) -> list[tuple[str, str]]:
    """(lokacja, opis) z pierwszej tury każdej wizyty. Wizyta = kolejne tury w tym samym miejscu."""
    out: list[tuple[str, str]] = []
    prev = None
    for r in answered(rows):
        if r["location"] != prev and r["scene_description"]:
            out.append((r["location"], r["scene_description"]))
        prev = r["location"]
    return out


def x2_scene(rows: list[dict]) -> dict:
    same_j, diff_j, same_c, diff_c = [], [], [], []
    v = visits(rows)
    for i in range(len(v)):
        for j in range(i + 1, len(v)):
            (loc_a, a), (loc_b, b) = v[i], v[j]
            (same_j if loc_a == loc_b else diff_j).append(jaccard(a, b))
            (same_c if loc_a == loc_b else diff_c).append(trigram_cosine(a, b))
    mean = lambda xs: statistics.fmean(xs) if xs else None
    return {"same_jaccard": mean(same_j), "diff_jaccard": mean(diff_j),
            "same_cosine": mean(same_c), "diff_cosine": mean(diff_c), "same_pairs": len(same_j)}


# --- X3: zmyślone byty i spójność mówiących ---

_CAPITAL = re.compile(r"[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]{2,}")
_OPENERS = " \t„\"“”«»'*(—–-"
# Formy grzecznościowe i zaimki pisane wielką literą w środku zdania to nie nowe byty
_STOP = {"ty", "twoj", "twoja", "twoje", "twojego", "twoim", "ciebie", "tobie", "cie", "pan", "pani",
         "panie", "panu", "wasz", "wasza", "wam", "was"}
# Mówiący, którym jest sam gracz (nie musi być w characters_present)
_PLAYER = {"ty", "ja", "bohater", "gracz", "narrator"}


def _prefixes(word: str) -> set[str]:
    w = fold(word)
    return {w[:k] for k in range(3, min(5, len(w)) + 1)}


def _key(word: str) -> str:
    w = fold(word)
    return w[:min(5, len(w))]


def capitalized_names(text: str) -> list[str]:
    """Słowa z wielkiej litery, które nie stoją na początku zdania ani wypowiedzi."""
    names = []
    for m in _CAPITAL.finditer(text):
        before = text[:m.start()].rstrip(_OPENERS)
        if before and before[-1] not in ".!?…:;\n":
            names.append(m.group())
    return names


def _world_words(world: World) -> set[str]:
    words: set[str] = set()

    def walk(value) -> None:
        if isinstance(value, str):
            words.update(re.findall(r"\w+", value))
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(world.model_dump())
    return words


def x3_entities(world: World, rows: list[dict]) -> dict:
    """Nowe nazwy własne: brak w YAML świata, w akcjach gracza i we wcześniejszych turach tej gry.

    Słowa porównujemy po prefiksie (do 5 liter), żeby odmiana („Borwina”, „Velgardzie”) nie liczyła się
    jako nowa nazwa. Każda nowa nazwa liczy się raz na grę.
    """
    known: set[str] = set()
    for w in _world_words(world):
        known |= _prefixes(w)
    player_names = {fold(w) for w in re.findall(r"\w+", world.player)}
    hits, turns_with_new = [], 0
    lines_total = lines_bad = 0
    for r in rows:
        for w in re.findall(r"\w+", r["player_action"]):
            known |= _prefixes(w)
        if r["error"] is not None:
            continue
        dialogue = json.loads(r["dialogue"] or "[]")
        texts = [r["narration"] or ""] + [d.get("text", "") for d in dialogue]
        candidates = [n for text in texts for n in capitalized_names(text)]
        candidates += [w for d in dialogue for w in _CAPITAL.findall(d.get("speaker", ""))]
        new_here = []
        for name in candidates:
            key = _key(name)
            if fold(name) in _STOP or key in known:
                continue
            new_here.append(name)
            known |= _prefixes(name)
        if new_here:
            turns_with_new += 1
            context = turn_text(r)
            hits += [{"t": r["t"], "name": n, "context": context} for n in new_here]
        for text in texts + [d.get("speaker", "") for d in dialogue]:
            for w in re.findall(r"\w+", text):
                known |= _prefixes(w)

        present = [fold(p) for p in characters_present(r)]
        for d in dialogue:
            speaker = fold(d.get("speaker", ""))
            if not speaker or speaker.split()[0] in _PLAYER | player_names:
                continue
            lines_total += 1
            if not any(speaker in p or p in speaker for p in present if p):
                lines_bad += 1
    return {"new_names": len(hits), "turns_with_new": turns_with_new, "turns": len(answered(rows)),
            "speaker_lines": lines_total, "speaker_bad": lines_bad, "hits": hits}


# --- X4: powtarzalność ---


def x4_repetition(rows: list[dict]) -> dict:
    """Trigramy słów tury t, które padły już w turze t-1 (odsetek), oraz distinct-2 całej gry."""
    by_t = {r["t"]: r for r in answered(rows)}
    overlaps = []
    for t, r in by_t.items():
        if t - 1 in by_t:
            cur = set(ngrams(tokens(turn_text(r)), 3))
            prev = set(ngrams(tokens(turn_text(by_t[t - 1])), 3))
            if cur:
                overlaps.append(len(cur & prev) / len(cur))
    bigrams = [g for r in by_t.values() for g in ngrams(tokens(turn_text(r)), 2)]
    return {"trigram_overlap": statistics.fmean(overlaps) if overlaps else None,
            "distinct2": len(set(bigrams)) / len(bigrams) if bigrams else None}


def fourgram_counts(rows: list[dict]) -> Counter:
    """W ilu turach padł dany 4-gram (każdy liczony raz na turę)."""
    counts: Counter = Counter()
    for r in answered(rows):
        counts.update(set(ngrams(tokens(turn_text(r)), 4)))
    return counts


# --- X5: wzrost kontekstu i koszt ---


def slope(xs: list[float], ys: list[float]) -> float | None:
    """Nachylenie prostej regresji (metoda najmniejszych kwadratów)."""
    if len(xs) < 2:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx if sxx else None


def x5_cost(rows: list[dict]) -> dict:
    return {
        "tokens_in_slope": slope([r["t"] for r in rows], [r["tokens_in"] for r in rows]),
        "tokens_in": sum(r["tokens_in"] for r in rows),
        "tokens_out": sum(r["tokens_out"] for r in rows),
        "time_s": sum(r["latency_ms"] for r in rows) / 1000,
        "final_facts": len(json.loads(rows[-1]["state_after"])) if rows else 0,
        "rejected": sum(len(json.loads(r["rejected_updates"])) for r in rows),
    }


# --- Statystyka ---


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% przedział ufności Wilsona dla odsetka k/n."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, center - half), min(1.0, center + half))


def binom_two_sided(k: int, n: int) -> float:
    """Dokładny dwustronny test dwumianowy z p = 0.5 (McNemar, test znaków)."""
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(k, n - k) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def mcnemar(pairs: list[tuple[bool, bool]]) -> dict:
    """pairs: (wynik ze stanem, wynik bez stanu). b, c = pary niezgodne."""
    b = sum(1 for a, z in pairs if a and not z)
    c = sum(1 for a, z in pairs if z and not a)
    return {"n": len(pairs), "b": b, "c": c, "p": binom_two_sided(b, b + c)}


def sign_test(diffs: list[float]) -> float:
    nonzero = [d for d in diffs if d != 0]
    return binom_two_sided(sum(d > 0 for d in nonzero), len(nonzero))


def bootstrap_mean(diffs: list[float], n: int = 10_000, seed: int = 0) -> dict:
    """Bootstrap par: średnia różnica, 95% przedział i dwustronne p (odsetek losowań po drugiej stronie 0)."""
    if len(diffs) < 2:  # z jednej pary nie da się nic losować
        return {"mean": statistics.fmean(diffs) if diffs else None, "lo": None, "hi": None, "p": None}
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(diffs, k=len(diffs))) for _ in range(n))
    below = sum(m <= 0 for m in means) / n
    above = sum(m >= 0 for m in means) / n
    return {"mean": statistics.fmean(diffs), "lo": means[int(0.025 * n)], "hi": means[int(0.975 * n) - 1],
            "p": min(1.0, 2 * min(below, above))}


# --- Gra i raport ---


def evaluate_game(scenario: Scenario, world: World, rows: list[dict]) -> dict:
    """Wszystkie metryki X jednej gry (rows: tury z bazy, Store.turns)."""
    return {
        "x1": x1_breakdown(scenario, world, rows),
        "x1_writes": x1_writes(scenario, world, rows),
        "x2": x2_scene(rows),
        "x3": x3_entities(world, rows),
        "x4": x4_repetition(rows),
        "x5": x5_cost(rows),
    }


def _fmt(x: float | None, digits: int = 2) -> str:
    return "brak" if x is None else f"{x:.{digits}f}"


def _pct(k: int, n: int) -> str:
    if not n:
        return "brak danych"
    lo, hi = wilson(k, n)
    return f"{100 * k / n:.0f}% ({k}/{n}, CI {100 * lo:.0f} do {100 * hi:.0f})"


def _mean_sd(xs: list[float | None], digits: int = 2) -> str:
    xs = [x for x in xs if x is not None]
    if not xs:
        return "brak"
    sd = statistics.stdev(xs) if len(xs) > 1 else 0.0
    return f"{statistics.fmean(xs):.{digits}f} ± {sd:.{digits}f}"


def _quantile(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, math.ceil(q * len(xs)) - 1)]


def config_summary(games: list[dict]) -> dict:
    """Zbiorcze liczby dla jednej konfiguracji (model × wariant). games: wyniki evaluate_game + rows."""
    probes = [p for g in games for p in g["x1"]]
    writes = [w for g in games for w in g["x1_writes"].values()]
    cell = Counter((p["written"], p["recalled"]) for p in probes)
    rows = [r for g in games for r in g["rows"]]
    later = [r["latency_ms"] / 1000 for r in rows if r["t"] > 1]
    first = [r["latency_ms"] / 1000 for r in rows if r["t"] == 1]
    x3 = [g["x3"] for g in games]
    return {
        "games": len(games),
        "write_k": sum(w["written"] for w in writes), "write_n": len(writes),
        "write_delayed": sum(w["delayed"] for w in writes),
        "cells": {"W+R+": cell[(True, True)], "W+R-": cell[(True, False)],
                  "W-R+": cell[(False, True)], "W-R-": cell[(False, False)]},
        "same": [g["x2"]["same_jaccard"] for g in games], "diff": [g["x2"]["diff_jaccard"] for g in games],
        "same_cos": [g["x2"]["same_cosine"] for g in games], "diff_cos": [g["x2"]["diff_cosine"] for g in games],
        "new_names": [x["new_names"] for x in x3],
        "turns_new_k": sum(x["turns_with_new"] for x in x3), "turns_n": sum(x["turns"] for x in x3),
        "speaker_bad": sum(x["speaker_bad"] for x in x3), "speaker_n": sum(x["speaker_lines"] for x in x3),
        "overlap": [g["x4"]["trigram_overlap"] for g in games], "distinct2": [g["x4"]["distinct2"] for g in games],
        "slope": [g["x5"]["tokens_in_slope"] for g in games],
        "tokens_in": [g["x5"]["tokens_in"] for g in games], "tokens_out": [g["x5"]["tokens_out"] for g in games],
        "time_s": [g["x5"]["time_s"] for g in games],
        "final_facts": [g["x5"]["final_facts"] for g in games], "rejected": [g["x5"]["rejected"] for g in games],
        "lat_median": statistics.median(later) if later else None, "lat_p95": _quantile(later, 0.95),
        "lat_first_median": statistics.median(first) if first else None,
        "json_first": sum(r["json_ok_first_try"] for r in rows), "turns_all": len(rows),
        "retries_mean": statistics.fmean([r["retries"] for r in rows]) if rows else None,
        "errors": sum(r["error"] is not None for r in rows),
    }


def print_summary(label: str, s: dict) -> None:
    c = s["cells"]
    gap = [a - b for a, b in zip(s["same"], s["diff"], strict=True) if a is not None and b is not None]
    gap_cos = [a - b for a, b in zip(s["same_cos"], s["diff_cos"], strict=True) if a is not None and b is not None]
    print("=" * 100)
    print(f"{label}  (ukończone gry: {s['games']})")
    print(f"  X1 zapis faktu w stanie    {_pct(s['write_k'], s['write_n'])}"
          f", w tym z opóźnieniem o 1 turę: {s['write_delayed']}")
    print(f"     M1 2×2: zapisał+pamięta {c['W+R+']}, zapisał+zapomniał {c['W+R-']}, "
          f"nie zapisał+pamięta {c['W-R+']}, nie zapisał+zapomniał {c['W-R-']}")
    print(f"  X2 opis lokacji (Jaccard)  ta sama {_mean_sd(s['same'])}, różne {_mean_sd(s['diff'])}, "
          f"różnica {_mean_sd(gap)}")
    print(f"     (cosinus trigramów)     ta sama {_mean_sd(s['same_cos'])}, różne {_mean_sd(s['diff_cos'])}, "
          f"różnica {_mean_sd(gap_cos)}")
    print(f"  X3 nowe nazwy na grę       {_mean_sd(s['new_names'])}, tury z nową nazwą "
          f"{_pct(s['turns_new_k'], s['turns_n'])}")
    print(f"     mówiący spoza obecnych  {_pct(s['speaker_bad'], s['speaker_n'])}")
    print(f"  X4 trigramy t/t-1          {_mean_sd(s['overlap'], 3)}, distinct-2 {_mean_sd(s['distinct2'], 3)}")
    print(f"  X5 nachylenie tokens_in    {_mean_sd(s['slope'], 0)} tok./turę")
    med = lambda xs: _fmt(statistics.median(xs), 0) if xs else "brak"
    print(f"     na grę (mediana)        wej. {med(s['tokens_in'])}, wyj. {med(s['tokens_out'])}, "
          f"czas {med(s['time_s'])} s")
    print(f"     fakty w stanie na końcu {_mean_sd(s['final_facts'], 1)}, odrzucone zmiany na grę "
          f"{_mean_sd(s['rejected'], 2)}")
    print(f"  Technicznie: JSON za 1. razem {_pct(s['json_first'], s['turns_all'])}, ponowienia "
          f"{_fmt(s['retries_mean'])}/turę, tury z błędem {s['errors']}, czas tury mediana "
          f"{_fmt(s['lat_median'], 1)} s, p95 {_fmt(s['lat_p95'], 1)} s, 1. tura mediana "
          f"{_fmt(s['lat_first_median'], 1)} s")


def paired_comparison(scenario: Scenario, by_seed: dict[tuple[str, bool], dict[int, dict]]) -> None:
    """Ze stanem minus bez stanu, na parach gier z tym samym modelem i seedem."""
    print("=" * 100)
    print("Wpływ stanu świata (ze stanem minus bez stanu, pary z tym samym seedem)")
    for model in sorted({m for m, _ in by_seed}):
        with_state, without = by_seed.get((model, True), {}), by_seed.get((model, False), {})
        seeds = sorted(with_state.keys() & without.keys())
        if not seeds:
            continue
        print(f"\n  {model}: {len(seeds)} par")

        def binary(metric: str, a: dict, b: dict) -> list[tuple[bool, bool]]:
            pick = lambda g: {(c.t, c.kind): c.passed for c in g["checks"]
                              if c.metric == metric and c.kind != "gaslight" and c.passed is not None}
            ca, cb = pick(a), pick(b)
            return [(ca[k], cb[k]) for k in ca.keys() & cb.keys()]

        for name, metric in (("M1", "m1_recall"), ("M2", "m2_immutable"), ("M4", "m4_location")):
            pairs = [p for s in seeds for p in binary(metric, with_state[s], without[s])]
            r = mcnemar(pairs)
            diff = (sum(a for a, _ in pairs) - sum(b for _, b in pairs)) / len(pairs) if pairs else 0
            print(f"    {name:<22} {100 * diff:+.0f} pp  (n={r['n']}, b={r['b']}, c={r['c']}, "
                  f"McNemar p={r['p']:.3f})")
        w_pairs = [(with_state[s]["x1_writes"][f]["written"], without[s]["x1_writes"][f]["written"])
                   for s in seeds for f in with_state[s]["x1_writes"].keys() & without[s]["x1_writes"].keys()]
        r = mcnemar(w_pairs)
        diff = (sum(a for a, _ in w_pairs) - sum(b for _, b in w_pairs)) / len(w_pairs) if w_pairs else 0
        print(f"    {'X1 zapis':<22} {100 * diff:+.0f} pp  (n={r['n']}, b={r['b']}, c={r['c']}, "
              f"McNemar p={r['p']:.3f})")
        numeric = (
            ("X3 nowe nazwy/grę", lambda g: g["x3"]["new_names"]),
            ("X4 trigramy t/t-1", lambda g: g["x4"]["trigram_overlap"]),
            ("X4 distinct-2", lambda g: g["x4"]["distinct2"]),
            ("tokeny wej./grę", lambda g: g["x5"]["tokens_in"]),
        )
        for name, get in numeric:
            diffs = [get(with_state[s]) - get(without[s]) for s in seeds
                     if get(with_state[s]) is not None and get(without[s]) is not None]
            b = bootstrap_mean(diffs)
            if b["mean"] is None:
                continue
            if b["p"] is None:
                print(f"    {name:<22} {b['mean']:+.3f}  (za mało par na test)")
                continue
            print(f"    {name:<22} {b['mean']:+.3f}  (95% {b['lo']:+.3f} do {b['hi']:+.3f}, bootstrap p={b['p']:.3f}, "
                  f"test znaków p={sign_test(diffs):.3f})")


def main() -> None:
    p = argparse.ArgumentParser(description="Dodatkowe metryki X1 do X5.")
    p.add_argument("--scenario", default="main_v2")
    p.add_argument("--tag", default=None)
    p.add_argument("--csv", help="zapisz metryki każdej gry do pliku CSV")
    p.add_argument("--names", type=int, default=0, help="pokaż N losowych trafień X3 do ręcznej oceny")
    p.add_argument("--all", action="store_true", help="licz też gry nieukończone (domyślnie tylko ukończone)")
    args = p.parse_args()

    scenario = load_scenario(args.scenario)
    world = load_world(scenario.world)
    store = Store(Path(settings.data_dir) / "dvn.sqlite")
    runs = [r for r in store.eval_runs(args.scenario, args.tag) if args.all or r["status"] == "done"]
    if not runs:
        print(f"Brak ukończonych uruchomień scenariusza {args.scenario}.")
        return

    by_config: dict[tuple[str, bool], list[dict]] = defaultdict(list)
    by_seed: dict[tuple[str, bool], dict[int, dict]] = defaultdict(dict)
    for run in runs:
        rows = store.turns(run["run_id"])
        game = evaluate_game(scenario, world, rows) | {"run": run, "rows": rows,
                                                      "checks": evaluate_run(scenario, rows)}
        key = (run["model"], bool(run["state_in_prompt"]))
        by_config[key].append(game)
        by_seed[key][run["seed"]] = game

    for (model, state), games in sorted(by_config.items()):
        print_summary(f"{model} | {'ze stanem' if state else 'BEZ stanu'}", config_summary(games))
        top = Counter()
        for g in games:
            top.update(fourgram_counts(g["rows"]))
        print("  X4 najczęstsze 4-gramy (liczba tur): "
              + "; ".join(f"„{' '.join(gram)}” {n}" for gram, n in top.most_common(10)))
    paired_comparison(scenario, by_seed)

    if args.names:
        hits = [(g["run"], h) for games in by_config.values() for g in games for h in g["x3"]["hits"]]
        print("=" * 100)
        print(f"X3: {min(args.names, len(hits))} losowych trafień z {len(hits)} (oceń ręcznie, czy to nowy byt)")
        for run, h in random.Random(0).sample(hits, min(args.names, len(hits))):
            context = " ".join(h["context"].split())
            i = context.find(h["name"])
            print(f"  [{run['model']} powt. {run['rep']} t{h['t']}] {h['name']}: …{context[max(0, i - 80):i + 80]}…")

    if args.csv:
        path = Path(args.csv)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["model", "state_in_prompt", "rep", "seed", "run_id", "status",
                             "x1_written", "x1_planted", "x1_wr_rr", "x1_wr_rf", "x1_nw_rr", "x1_nw_rf",
                             "x2_same_jaccard", "x2_diff_jaccard", "x2_same_cosine", "x2_diff_cosine",
                             "x3_new_names", "x3_turns_with_new", "x3_turns", "x3_speaker_bad", "x3_speaker_lines",
                             "x4_trigram_overlap", "x4_distinct2", "x5_tokens_in_slope", "x5_tokens_in",
                             "x5_tokens_out", "x5_time_s", "x5_final_facts", "x5_rejected"])
            for games in by_config.values():
                for g in games:
                    run, cells = g["run"], Counter((p["written"], p["recalled"]) for p in g["x1"])
                    writer.writerow([
                        run["model"], run["state_in_prompt"], run["rep"], run["seed"], run["run_id"], run["status"],
                        sum(w["written"] for w in g["x1_writes"].values()), len(g["x1_writes"]),
                        cells[(True, True)], cells[(True, False)], cells[(False, True)], cells[(False, False)],
                        g["x2"]["same_jaccard"], g["x2"]["diff_jaccard"], g["x2"]["same_cosine"],
                        g["x2"]["diff_cosine"], g["x3"]["new_names"], g["x3"]["turns_with_new"], g["x3"]["turns"],
                        g["x3"]["speaker_bad"], g["x3"]["speaker_lines"], g["x4"]["trigram_overlap"],
                        g["x4"]["distinct2"], g["x5"]["tokens_in_slope"], g["x5"]["tokens_in"],
                        g["x5"]["tokens_out"], g["x5"]["time_s"], g["x5"]["final_facts"], g["x5"]["rejected"],
                    ])
        print(f"\nZapisano metryki {len(runs)} gier do {path}")


if __name__ == "__main__":
    main()
