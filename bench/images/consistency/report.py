"""Raport HTML z wyników run.py (i score.py, jeśli był uruchomiony). Tylko biblioteka standardowa.

  python report.py --out ~/data/dvn/consistency      # zapisuje report.html w tym katalogu
"""

import argparse
import csv
import html
import json
import statistics
from collections import defaultdict
from pathlib import Path


def mean(values: list[float]) -> str:
    return f"{statistics.fmean(values):.3f}" if values else "-"


def table(headers: list[str], rows: list[list]) -> str:
    head = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def build(out: Path) -> str:
    records = [json.loads(line) for line in (out / "results.jsonl").read_text(encoding="utf-8").splitlines() if line]
    parts = ["<h1>Spójność obrazów</h1>"]

    # Czas i pamięć
    rows = []
    for model in sorted({r["model"] for r in records}):
        scenes = [r["seconds"] for r in records if r["model"] == model and r["kind"] == "scene"]
        vram = [r.get("vram_peak_gb") or 0 for r in records if r["model"] == model]
        rows.append([model, len(scenes), f"{statistics.median(scenes):.1f}" if scenes else "-", f"{max(vram):.1f}"])
    parts += ["<h2>Czas i pamięć</h2>", table(["model", "sceny", "mediana s/obraz", "szczyt VRAM GB"], rows)]

    # Oceny (po score.py)
    scores_path = out / "scores.csv"
    if scores_path.exists():
        scores = list(csv.DictReader(scores_path.open(encoding="utf-8")))
        groups = defaultdict(list)
        for s in scores:
            groups[(s["model"], s["variant"], s["entity_kind"])].append(s)
        rows = [[m, v, kind, len(g), mean([float(s["dino"]) for s in g]), mean([float(s["clip"]) for s in g]),
                 mean([float(s["clipscore"]) for s in g])] for (m, v, kind), g in sorted(groups.items())]
        parts += ["<h2>Podobieństwo do wzorca (średnio)</h2>",
                  "<p>dino i clip: cosinus ze wzorcem, wyżej = bardziej podobne. clipscore: zgodność z opisem sceny.</p>",
                  table(["model", "wariant", "co", "n", "dino", "clip", "clipscore"], rows)]
        drift = defaultdict(list)
        for s in scores:
            if s["entity_kind"] == "character":
                drift[(s["model"], s["variant"], int(s["k"]))].append(float(s["dino"]))
        ks = sorted({k for _, _, k in drift})
        rows = [[m, v, *[mean(drift.get((m, v, k), [])) for k in ks]]
                for m, v in sorted({(m, v) for m, v, _ in drift})]
        parts += ["<h2>Rozjeżdżanie się postaci: dino w zależności od k (k-te pojawienie się postaci)</h2>",
                  table(["model", "wariant", *[f"k={k}" for k in ks]], rows)]
    else:
        parts.append("<p>Brak scores.csv: uruchom score.py, żeby zobaczyć oceny.</p>")

    # Obrazy obok siebie (pierwszy seed każdego modelu)
    parts.append("<h2>Obrazy (pierwszy seed)</h2>")
    for model in sorted({r["model"] for r in records}):
        seed = min(r["seed"] for r in records if r["model"] == model)
        mine = [r for r in records if r["model"] == model and r["seed"] == seed]
        parts.append(f"<h3>{html.escape(model)}, seed {seed}</h3>")
        anchors = [r for r in mine if r["kind"] == "anchor"]
        parts.append(row_html("wzorce", anchors, lambda r: r["entity"]))
        for variant in ("text", "anchor", "chain"):
            scenes = sorted((r for r in mine if r.get("variant") == variant), key=lambda r: r["scene"])
            if scenes:
                parts.append(row_html(variant, scenes, lambda r: f"{r['scene']}: {r['location']}, "
                                      f"{', '.join(r['characters'])}"))
    style = ("body{font-family:sans-serif;margin:24px}table{border-collapse:collapse;margin:8px 0}"
             "td,th{border:1px solid #ccc;padding:4px 8px}.row{display:flex;gap:6px;overflow-x:auto}"
             "figure{margin:0;font-size:12px;width:220px}img{width:220px}")
    return f"<!doctype html><meta charset='utf-8'><title>Spójność obrazów</title><style>{style}</style>" + "".join(parts)


def row_html(label: str, records: list[dict], caption) -> str:
    figs = "".join(f"<figure><img src='{html.escape(r['path'])}' loading='lazy'>"
                   f"<figcaption>{html.escape(caption(r))} ({r['seconds']} s)</figcaption></figure>" for r in records)
    return f"<h4>{html.escape(label)}</h4><div class='row'>{figs}</div>"


def main() -> None:
    p = argparse.ArgumentParser(description="Raport HTML z wyników pomiaru spójności obrazów.")
    p.add_argument("--out", required=True)
    out = Path(p.parse_args().out).expanduser()
    (out / "report.html").write_text(build(out), encoding="utf-8")
    print(f"Zapisano {out / 'report.html'}")


if __name__ == "__main__":
    main()
