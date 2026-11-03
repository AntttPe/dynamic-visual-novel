"""Pomiar KV cache (cache prefiksu promptu) przez czas do pierwszego tokenu (TTFT).

Te same 4 scenariusze co w nocie prowadzącego, ale na prawdziwych promptach z naszej gry:
  cold        prompt pierwszy raz (unikalny znacznik na początku, więc nic nie ma w cache)
  warm        ten sam prompt jeszcze raz (cały powinien być w cache)
  append      prompt plus następna tura gry dopisana na końcu (tak działa full_cached)
  invalidate  ten sam prompt ze zmienionym znacznikiem na początku (cache nie powinien zadziałać)

Prompt jest składany jak w pamięci full_cached: prompt systemowy, potem wiadomości gracza
(dokładnie tak, jak były wysłane) i odpowiedzi narratora z jednej zapisanej gry, aż do zadanej długości.

Użycie (w kontenerze, wymaga VPN):
  python -m app.eval.kv_cache --models openai/strata-big openai/large-reasoning --reps 3
  python -m app.eval.kv_cache --summary data/eval/kv_cache.csv     # sama tabela z zapisanych wyników

Wyniki dopisywane do CSV. Ponowne uruchomienie tej samej komendy pomija ukończone powtórzenia.
"""

import argparse
import asyncio
import csv
import json
import sqlite3
import statistics
import uuid
from collections import defaultdict
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.core.engine import NARRATOR_SCHEMA
from app.llm.base import LLMClient, LLMError
from app.llm.litellm_client import LiteLLMClient

SCENARIOS = ("cold", "warm", "append", "invalidate")
FIELDS = ["measured_at", "tag", "model", "size", "rep", "scenario", "messages", "tokens_in", "tokens_cached",
          "ttft_ms", "latency_ms", "error"]
CHARS_PER_TOKEN = 3.0  # przybliżenie dla polskiego tekstu (z bazy: 2,8 do 3,3 znaku na token)
BACKOFF_S = (10, 30, 60, 120)  # przerwy przed ponowieniem powtórzenia, gdy model nie odpowiada


def estimate_tokens(messages: list[dict]) -> int:
    return int(sum(len(m["content"]) for m in messages) / CHARS_PER_TOKEN)


def pick_run(db_path: str | Path, run_id: str | None = None) -> str:
    """Gra, z której bierzemy prompty: podana albo najdłuższa gra strata-big ze stanem w prompcie."""
    if run_id:
        return run_id
    with closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute(
            "SELECT t.run_id FROM turns t JOIN runs r USING (run_id)"
            " WHERE r.model = 'openai/strata-big' AND r.state_in_prompt = 1 AND t.error IS NULL"
            " GROUP BY t.run_id ORDER BY count(*) DESC, sum(length(t.raw_output)) DESC LIMIT 1"
        ).fetchone()
    if not row:
        raise SystemExit("W bazie nie ma gry strata-big ze stanem. Podaj --run-id.")
    return row[0]


def load_turns(db_path: str | Path, run_id: str) -> list[dict]:
    with closing(sqlite3.connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT prompt, raw_output FROM turns WHERE run_id = ? AND error IS NULL ORDER BY t", (run_id,)
        ).fetchall()
    if not rows:
        raise SystemExit(f"Brak tur dla gry {run_id}")
    return [{"prompt": json.loads(p), "raw_output": raw} for p, raw in rows]


def build_conversation(turns: list[dict], target_tokens: int) -> tuple[list[dict], list[dict]]:
    """Składa rozmowę w układzie full_cached o długości co najmniej target_tokens (szacunek).

    Zwraca (prompt, dopisek): prompt kończy się wiadomością gracza, a dopisek to odpowiedź narratora
    na nią i następna wiadomość gracza, czyli dokładnie to, o co urośnie prompt w kolejnej turze.
    """
    messages = [turns[0]["prompt"][0]]  # prompt systemowy
    for i, turn in enumerate(turns[:-1]):
        messages.append({"role": "user", "content": turn["prompt"][-1]["content"]})
        if estimate_tokens(messages) >= target_tokens:
            follow_up = [{"role": "assistant", "content": turn["raw_output"]},
                         {"role": "user", "content": turns[i + 1]["prompt"][-1]["content"]}]
            return messages, follow_up
        messages.append({"role": "assistant", "content": turn["raw_output"]})
    raise SystemExit(f"Gra jest za krótka na {target_tokens} tokenów (ok. {estimate_tokens(messages)}). "
                     "Wybierz mniejszy --sizes albo inną grę (--run-id).")


def with_marker(messages: list[dict], marker: str) -> list[dict]:
    """Kopia rozmowy ze znacznikiem na początku promptu systemowego (zmienia pierwszy token)."""
    first = {**messages[0], "content": f"[pomiar {marker}]\n{messages[0]['content']}"}
    return [first, *messages[1:]]


def scenario_prompts(messages: list[dict], follow_up: list[dict]) -> dict[str, list[dict]]:
    """Prompty 4 scenariuszy w kolejności wysyłania. Nowe znaczniki przy każdym wywołaniu."""
    marker = uuid.uuid4().hex[:12]
    base = with_marker(messages, marker)
    return {
        "cold": base,
        "warm": base,
        "append": base + follow_up,
        "invalidate": with_marker(messages, uuid.uuid4().hex[:12]),
    }


def done_reps(csv_path: Path, tag: str) -> set[tuple[str, int, int]]:
    """Powtórzenia (model, rozmiar, rep) z kompletem 4 scenariuszy bez błędu."""
    if not csv_path.exists():
        return set()
    ok = defaultdict(set)
    with csv_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["tag"] == tag and not row["error"]:
                ok[(row["model"], int(row["size"]), int(row["rep"]))].add(row["scenario"])
    return {key for key, scen in ok.items() if scen >= set(SCENARIOS)}


async def measure_rep(client: LLMClient, messages: list[dict], follow_up: list[dict], *,
                      use_schema: bool, max_tokens: int, pause_s: float) -> list[dict]:
    """Jedno powtórzenie: 4 scenariusze po kolei. LLMError przerywa całe powtórzenie."""
    rows = []
    for scenario, prompt in scenario_prompts(messages, follow_up).items():
        result = await client.complete(
            prompt,
            json_schema=NARRATOR_SCHEMA if use_schema else None,
            temperature=0.0,
            seed=1,
            max_tokens=max_tokens,
        )
        rows.append({
            "measured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "scenario": scenario,
            "messages": len(prompt),
            "tokens_in": result.tokens_in,
            "tokens_cached": result.tokens_cached,
            "ttft_ms": round(result.ttft_ms, 1) if result.ttft_ms is not None else "",
            "latency_ms": round(result.latency_ms, 1),
            "error": "",
        })
        if pause_s:
            await asyncio.sleep(pause_s)
    return rows


ClientFactory = Callable[[str], LLMClient]


def default_client(model: str) -> LLMClient:
    # Strumień jest potrzebny do TTFT niezależnie od ustawienia gry
    return LiteLLMClient(model, settings.model_copy(update={"narrator_stream": True}))


async def run(models: list[str], sizes: list[int], reps: int, turns: list[dict], csv_path: Path, *,
              tag: str = "", use_schema: bool = False, max_tokens: int = 1, pause_s: float = 1.0,
              backoff_s: tuple[float, ...] = BACKOFF_S, client_factory: ClientFactory = default_client) -> int:
    """Macierz powtórzenia × modele × rozmiary. Zwraca liczbę powtórzeń, których nie udało się zmierzyć."""
    conversations = {size: build_conversation(turns, size) for size in sizes}
    clients = {model: client_factory(model) for model in models}
    skip = done_reps(csv_path, tag)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not csv_path.exists()
    failed = 0
    with csv_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        # Powtórzenia na zewnątrz, żeby zmiany obciążenia serwera rozłożyły się na wszystkie warianty
        for rep in range(1, reps + 1):
            for model in models:
                for size in sizes:
                    if (model, size, rep) in skip:
                        continue
                    messages, follow_up = conversations[size]
                    for attempt, wait in enumerate((0, *backoff_s)):
                        if wait:
                            print(f"  czekam {wait:.0f} s i ponawiam (próba {attempt + 1})", flush=True)
                            await asyncio.sleep(wait)
                        try:
                            rows = await measure_rep(clients[model], messages, follow_up,
                                                     use_schema=use_schema, max_tokens=max_tokens, pause_s=pause_s)
                            break
                        except LLMError as e:
                            print(f"  {model} {size} rep {rep}: {str(e)[:200]}", flush=True)
                    else:
                        failed += 1
                        continue
                    for row in rows:
                        writer.writerow({"tag": tag, "model": model, "size": size, "rep": rep, **row})
                    f.flush()
                    ttfts = ", ".join(f"{r['scenario']} {r['ttft_ms']}" for r in rows)
                    print(f"{model} {size} rep {rep}: tokeny {rows[0]['tokens_in']}, TTFT ms: {ttfts}", flush=True)
    return failed


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _fmt_ms(value: float | None) -> str:
    return "" if value is None else f"{value:,.0f}".replace(",", " ")


def summary(csv_path: Path, tag: str | None = None) -> str:
    """Tabela jak w nocie prowadzącego: mediana TTFT na model, długość i scenariusz."""
    groups: dict[tuple[str, int], dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    with csv_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["error"] or row["ttft_ms"] == "" or (tag is not None and row["tag"] != tag):
                continue
            groups[(row["model"], int(row["size"]))][row["scenario"]].append(row)
    lines = ["| model | długość | tokeny | cold | warm | przyspieszenie | append | invalidate | cached (warm) | n |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for (model, size), by_scen in sorted(groups.items()):
        ttft = {s: _median([float(r["ttft_ms"]) for r in by_scen.get(s, [])]) for s in SCENARIOS}
        tokens = _median([int(r["tokens_in"]) for r in by_scen.get("cold", [])])
        cached = _median([int(r["tokens_cached"]) for r in by_scen.get("warm", [])])
        speedup = f"{ttft['cold'] / ttft['warm']:.1f}x" if ttft["cold"] and ttft["warm"] else ""
        n = min(len(by_scen.get(s, [])) for s in SCENARIOS)
        lines.append(f"| {model.split('/')[-1]} | {size / 1000:g}k | {tokens or ''} | {_fmt_ms(ttft['cold'])} | "
                     f"{_fmt_ms(ttft['warm'])} | {speedup} | {_fmt_ms(ttft['append'])} | "
                     f"{_fmt_ms(ttft['invalidate'])} | {cached if cached is not None else ''} | {n} |")
    return "\n".join(lines) + "\n\nTTFT w ms (mediana). cached: tokeny z cache zgłoszone przez serwer (vLLM zgłasza 0)."


def main() -> None:
    p = argparse.ArgumentParser(description="Pomiar KV cache przez TTFT na promptach z gry")
    p.add_argument("--models", nargs="+", default=["openai/strata-big", "openai/large-reasoning"])
    p.add_argument("--sizes", nargs="+", type=int, default=[2000, 4000, 8000, 11000],
                   help="docelowe długości promptu w tokenach (szacunek, prawdziwa liczba trafia do CSV);"
                        " cała gra main_v2 (28 tur) to ok. 11,5k")
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--db", default=str(Path(settings.data_dir) / "dvn.sqlite"))
    p.add_argument("--run-id", help="gra, z której składamy prompty (domyślnie najdłuższa strata-big ze stanem)")
    p.add_argument("--csv", default=str(Path(settings.data_dir) / "eval" / "kv_cache.csv"))
    p.add_argument("--tag", default="", help="nazwa pomiaru, np. kv1")
    p.add_argument("--max-tokens", type=int, default=1, help="długość odpowiedzi (TTFT nie zależy od niej)")
    p.add_argument("--schema", action="store_true",
                   help="wymuszony JSON jak w grze (strata-big odrzuca go przy krótkiej odpowiedzi, wtedy"
                        " zwiększ --max-tokens)")
    p.add_argument("--pause", type=float, default=1.0, help="przerwa między zapytaniami w sekundach")
    p.add_argument("--summary", metavar="CSV", help="tylko pokaż tabelę z zapisanych wyników")
    args = p.parse_args()

    if args.summary:
        print(summary(Path(args.summary), args.tag or None))
        return
    run_id = pick_run(args.db, args.run_id)
    turns = load_turns(args.db, run_id)
    print(f"Prompty z gry {run_id} ({len(turns)} tur). Wyniki: {args.csv}")
    for size in args.sizes:
        messages, _ = build_conversation(turns, size)
        print(f"  {size} tokenów: {len(messages)} wiadomości, szacunek {estimate_tokens(messages)}")
    failed = asyncio.run(run(args.models, args.sizes, args.reps, turns, Path(args.csv), tag=args.tag,
                             use_schema=args.schema, max_tokens=args.max_tokens, pause_s=args.pause))
    print()
    print(summary(Path(args.csv), args.tag))
    if failed:
        print(f"\n{failed} powtórzeń bez wyniku (model nie odpowiadał). Uruchom tę samą komendę ponownie.")


if __name__ == "__main__":
    main()
