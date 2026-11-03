"""Pomiar spójności postaci i lokacji w obrazach (zadanie Z1).

Dla każdego modelu i seeda: obrazy wzorcowe postaci i lokacji, potem każda scena w wariantach
text, anchor i chain (opis w testset.yaml). Wynik: obrazy i results.jsonl (jedna linia na obraz).
Ponowne uruchomienie tej samej komendy pomija gotowe obrazy, więc po przerwaniu wystarczy ją powtórzyć.

  python run.py --models flux2-klein-4b --seeds 1 --scenes 3 --out ~/data/dvn/consistency   # krótki test
  python run.py --models sdxl-ip flux2-klein-4b flux3-klein --out ~/data/dvn/consistency     # pełny pomiar
  python run.py --models fake --out /tmp/test                                                # bez GPU
"""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml
from models import make_adapter

HERE = Path(__file__).resolve().parent
VARIANTS = ("text", "anchor", "chain")
SEEDS = (1001, 1002, 1003)


def load_testset(path: Path) -> dict:
    ts = yaml.safe_load(path.read_text(encoding="utf-8"))
    for i, scene in enumerate(ts["scenes"], start=1):
        if scene["location"] not in ts["locations"]:
            raise SystemExit(f"Scena {i}: nieznana lokacja {scene['location']}")
        for c in scene["characters"]:
            if c not in ts["characters"]:
                raise SystemExit(f"Scena {i}: nieznana postać {c}")
    return ts


def anchor_prompt(ts: dict, kind: str, key: str) -> str:
    if kind == "character":
        return f"{ts['style']}. Character reference: {ts['characters'][key]['description']}, full body, plain background"
    return f"{ts['style']}. Background, no people: {ts['locations'][key]['description']}"


def scene_prompt(ts: dict, scene: dict) -> str:
    """Pełne opisy postaci i miejsca także w wariantach z obrazem, żeby różnił się tylko obraz wejściowy."""
    people = "; ".join(ts["characters"][c]["description"] for c in scene["characters"])
    return (f"{ts['style']}. {scene['action']}. Characters: {people}. "
            f"Place: {ts['locations'][scene['location']]['description']}")


class Results:
    """results.jsonl: jedna linia na gotowy obraz. Klucz pozwala pominąć obraz przy wznowieniu."""

    def __init__(self, path: Path):
        self.path = path
        self.done: set[str] = set()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.done.add(json.loads(line)["key"])

    def add(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.done.add(record["key"])


def jobs(ts: dict, model: str, seed: int, variants: list[str], n_scenes: int):
    """Kolejność: wzorce, potem sceny wariant po wariancie. Zwraca opisy zadań bez generowania."""
    base = Path(model) / f"seed{seed}"
    anchors = {}
    for kind, group in (("character", "characters"), ("location", "locations")):
        for key in ts[group]:
            path = base / "anchors" / f"{key}.png"
            anchors[key] = path
            yield {"kind": "anchor", "entity": key, "entity_kind": kind, "prompt": anchor_prompt(ts, kind, key),
                   "refs": [], "path": path}
    for variant in variants:
        latest = dict(anchors)  # dla chain: ostatni obraz z daną postacią lub lokacją
        seen: dict[str, int] = {}
        for i, scene in enumerate(ts["scenes"][:n_scenes], start=1):
            entities = [*scene["characters"], scene["location"]]
            for e in entities:
                seen[e] = seen.get(e, 0) + 1
            refs = [] if variant == "text" else [(anchors if variant == "anchor" else latest)[e] for e in entities]
            path = base / variant / f"scene{i:02d}.png"
            yield {"kind": "scene", "variant": variant, "scene": i, "location": scene["location"],
                   "characters": scene["characters"], "k": {e: seen[e] for e in entities},
                   "prompt": scene_prompt(ts, scene), "refs": refs, "path": path}
            if variant == "chain":
                for e in entities:
                    latest[e] = path


def run(ts: dict, models: list[str], seeds: list[int], variants: list[str], out: Path, *,
        n_scenes: int | None = None, adapters: dict | None = None, log=print) -> Results:
    out.mkdir(parents=True, exist_ok=True)
    results = Results(out / "results.jsonl")
    n_scenes = n_scenes or len(ts["scenes"])
    size = tuple(ts["size"])
    for model in models:
        todo = [(seed, job) for seed in seeds for job in jobs(ts, model, seed, variants, n_scenes)]
        todo = [(seed, job) for seed, job in todo if key_of(ts, model, seed, job) not in results.done]
        if not todo:
            log(f"[{model}] wszystko gotowe, pomijam")
            continue
        adapter = (adapters or {}).get(model) or make_adapter(model)
        t0 = time.perf_counter()
        adapter.load()
        log(f"[{model}] model wczytany w {time.perf_counter() - t0:.0f} s, do zrobienia {len(todo)} obrazów")
        try:
            for n, (seed, job) in enumerate(todo, start=1):
                path = out / job["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                refs = [out / r for r in job["refs"]][: adapter.max_refs]
                t1 = time.perf_counter()
                extra = adapter.generate(job["prompt"], refs, seed, path, size)
                seconds = time.perf_counter() - t1
                record = {"key": key_of(ts, model, seed, job), "testset": f"{ts['id']}/v{ts['version']}",
                          "model": model, "seed": seed, **job, "path": str(job["path"]),
                          "refs": [str(r) for r in job["refs"][: adapter.max_refs]],
                          "seconds": round(seconds, 2), "time": datetime.now(UTC).isoformat(timespec="seconds"),
                          **extra}
                results.add(record)
                name = job.get("entity") or f"{job['variant']} scena {job['scene']}"
                log(f"[{model}] {n}/{len(todo)} seed {seed} {name}: {seconds:.1f} s, "
                    f"VRAM {extra.get('vram_peak_gb', 0)} GB")
        finally:
            adapter.unload()
    return results


def key_of(ts: dict, model: str, seed: int, job: dict) -> str:
    return f"{ts['id']}/v{ts['version']}/{model}/seed{seed}/{job['path'].relative_to(Path(model) / f'seed{seed}')}"


def main() -> None:
    p = argparse.ArgumentParser(description="Pomiar spójności postaci i lokacji w obrazach.")
    p.add_argument("--models", nargs="+", required=True, help="sdxl-ip, flux2-klein-4b, flux3-klein albo fake")
    p.add_argument("--seeds", type=int, default=len(SEEDS), help="ile seedów (1 do 3)")
    p.add_argument("--scenes", type=int, help="tylko pierwsze N scen (krótki test)")
    p.add_argument("--variants", nargs="+", default=list(VARIANTS), choices=VARIANTS)
    p.add_argument("--testset", default=str(HERE / "testset.yaml"))
    p.add_argument("--out", required=True, help="katalog wyników, na serwerze w ~/data")
    args = p.parse_args()
    ts = load_testset(Path(args.testset))
    out = Path(args.out).expanduser()
    run(ts, args.models, list(SEEDS[: args.seeds]), args.variants, out, n_scenes=args.scenes)
    print(f"\nGotowe. Oceny: python score.py --out {out}   Raport: python report.py --out {out}")


if __name__ == "__main__":
    main()
