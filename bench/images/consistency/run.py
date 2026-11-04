"""Pomiar spójności postaci i lokacji w obrazach (zadanie Z1).

Dla każdego modelu i seeda: obrazy wzorcowe postaci i lokacji, potem każda scena w wariantach
text, anchor, chain i layers (opis w testset.yaml). Wynik: obrazy i results.jsonl (jedna linia na obraz).
Ponowne uruchomienie tej samej komendy pomija gotowe obrazy, więc po przerwaniu wystarczy ją powtórzyć.

  python run.py --models flux2-klein-4b --seeds 1 --scenes 3 --out ~/data/dvn-results/consistency-test
  python run.py --models sdxl-ip flux2-klein-4b flux3-klein --out ~/data/dvn-results/consistency
  python run.py --models fake --out /tmp/test                                       # bez GPU
"""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml
from compose import Composer
from models import make_adapter

HERE = Path(__file__).resolve().parent
VARIANTS = ("text", "anchor", "chain", "layers")
SEEDS = (1001, 2001, 3001)


def load_testset(path: Path) -> dict:
    ts = yaml.safe_load(path.read_text(encoding="utf-8"))
    for i, scene in enumerate(ts["scenes"], start=1):
        if scene["location"] not in ts["locations"]:
            raise SystemExit(f"Scena {i}: nieznana lokacja {scene['location']}")
        for c in scene["characters"]:
            if c not in ts["characters"]:
                raise SystemExit(f"Scena {i}: nieznana postać {c}")
        if "return_of" in scene:
            j = scene["return_of"]
            if not 1 <= j < i:
                raise SystemExit(f"Scena {i}: return_of musi wskazywać wcześniejszą scenę")
            first = ts["scenes"][j - 1]
            if any(first[f] != scene[f] for f in ("location", "characters", "action")):
                raise SystemExit(f"Scena {i}: powrót musi mieć to samo miejsce, postacie i akcję co scena {j}")
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


def sprite_prompt(ts: dict, scene: dict, character: str) -> str:
    return (f"{ts['style']}. Character sprite: {ts['characters'][character]['description']}. "
            f"Pose for the scene: {scene['action']}. Full body, plain light grey background, no scenery")


class Results:
    """results.jsonl: jedna linia na gotowy obraz. Klucz pozwala pominąć obraz przy wznowieniu."""

    def __init__(self, path: Path):
        self.path = path
        self.records: dict[str, dict] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    self.records[record["key"]] = record

    @property
    def done(self) -> set[str]:
        return set(self.records)

    def add(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.records[record["key"]] = record


def jobs(ts: dict, model: str, seed: int, variants: list[str], n_scenes: int):
    """Kolejność: wzorce, potem sceny wariant po wariancie. Każda scena ma własny seed (seed + numer sceny),
    taki sam we wszystkich wariantach, więc warianty różnią się tylko obrazami wejściowymi."""
    base = Path(model) / f"seed{seed}"
    anchors = {}
    for kind, group in (("character", "characters"), ("location", "locations")):
        for key in ts[group]:
            path = base / "anchors" / f"{key}.png"
            anchors[key] = path
            yield {"kind": "anchor", "entity": key, "entity_kind": kind, "prompt": anchor_prompt(ts, kind, key),
                   "refs": [], "path": path, "image_seed": seed}
    characters = list(ts["characters"])
    for variant in variants:
        latest = dict(anchors)  # dla chain: ostatni obraz z daną postacią lub lokacją
        seen: dict[str, int] = {}
        for i, scene in enumerate(ts["scenes"][:n_scenes], start=1):
            entities = [*scene["characters"], scene["location"]]
            for e in entities:
                seen[e] = seen.get(e, 0) + 1
            info = {"variant": variant, "scene": i, "location": scene["location"],
                    "characters": scene["characters"], "k": {e: seen[e] for e in entities},
                    "return_of": scene.get("return_of"), "prompt": scene_prompt(ts, scene)}
            path = base / variant / f"scene{i:02d}.png"
            if variant == "layers":
                sprites = []
                for c in scene["characters"]:
                    sprite = base / "layers" / "sprites" / f"scene{i:02d}_{c}.png"
                    sprites.append(sprite)
                    yield {"kind": "sprite", "variant": variant, "scene": i, "entity": c,
                           "prompt": sprite_prompt(ts, scene, c), "refs": [anchors[c]], "path": sprite,
                           "image_seed": seed + i + 1000 * (characters.index(c) + 1)}
                yield {"kind": "scene", **info, "compose": True, "refs": [anchors[scene["location"]], *sprites],
                       "path": path, "image_seed": None}
                continue
            refs = [] if variant == "text" else [(anchors if variant == "anchor" else latest)[e] for e in entities]
            yield {"kind": "scene", **info, "refs": refs, "path": path, "image_seed": seed + i}
            if variant == "chain":
                for e in entities:
                    latest[e] = path


def key_of(ts: dict, model: str, seed: int, job: dict) -> str:
    return f"{ts['id']}/v{ts['version']}/{model}/seed{seed}/{job['path'].relative_to(Path(model) / f'seed{seed}')}"


def run(ts: dict, models: list[str], seeds: list[int], variants: list[str], out: Path, *,
        n_scenes: int | None = None, adapters: dict | None = None, composer=None, log=print) -> Results:
    out.mkdir(parents=True, exist_ok=True)
    results = Results(out / "results.jsonl")
    n_scenes = n_scenes or len(ts["scenes"])
    size = tuple(ts["size"])
    composer = composer or Composer()
    for model in models:
        todo = [(seed, job) for seed in seeds for job in jobs(ts, model, seed, variants, n_scenes)]
        todo = [(seed, job) for seed, job in todo if key_of(ts, model, seed, job) not in results.records]
        if not todo:
            log(f"[{model}] wszystko gotowe, pomijam")
            continue
        adapter = (adapters or {}).get(model) or make_adapter(model)
        if any(not job.get("compose") for _, job in todo):
            t0 = time.perf_counter()
            adapter.load()
            log(f"[{model}] model wczytany w {time.perf_counter() - t0:.0f} s, do zrobienia {len(todo)} obrazów")
        try:
            for n, (seed, job) in enumerate(todo, start=1):
                path = out / job["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                t1 = time.perf_counter()
                if job.get("compose"):
                    refs = job["refs"]
                    extra = composer.compose(out / refs[0], [out / r for r in refs[1:]], path, size)
                else:
                    refs = job["refs"][: adapter.max_refs]
                    extra = adapter.generate(job["prompt"], [out / r for r in refs], job["image_seed"], path, size)
                seconds = round(time.perf_counter() - t1, 2)
                record = {"key": key_of(ts, model, seed, job), "testset": f"{ts['id']}/v{ts['version']}",
                          "model": model, "seed": seed, **job, "path": str(job["path"]),
                          "refs": [str(r) for r in refs], "seconds": seconds,
                          "time": datetime.now(UTC).isoformat(timespec="seconds"), **extra}
                if job.get("compose"):
                    # Koszt sceny w layers: obrazy postaci + składanie (tło jest z cache, czyli wzorzec lokacji)
                    sprite_s = sum(results.records[key_of(ts, model, seed, {"path": Path(r)})]["seconds"]
                                   for r in refs[1:])
                    record["seconds_total"] = round(seconds + sprite_s, 2)
                results.add(record)
                name = job.get("entity") or f"{job['variant']} scena {job['scene']}"
                if job["kind"] == "sprite":
                    name = f"layers scena {job['scene']} postać {job['entity']}"
                log(f"[{model}] {n}/{len(todo)} seed {seed} {name}: {seconds:.1f} s, "
                    f"VRAM {extra.get('vram_peak_gb', 0)} GB")
        finally:
            adapter.unload()
    return results


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
