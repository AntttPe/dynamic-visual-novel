"""Raport HTML z wyników run.py i score.py. Tylko biblioteka standardowa.

  python report.py --out ~/data/dvn-results/consistency      # zapisuje report.html w tym katalogu
"""

import argparse
import csv
import html
import json
import statistics
from pathlib import Path

VARIANTS = ("text", "anchor", "chain", "layers")
VARIANT_NAMES = {"text": "sam tekst", "anchor": "obraz wzorcowy", "chain": "łańcuch", "layers": "warstwy (VN)"}
K_BUCKETS = ((2, 5), (6, 10), (11, 15), (16, 22))


def num(value) -> float | None:
    return float(value) if value not in ("", None) else None


def mean(values) -> str:
    values = [v for v in values if v is not None]
    return f"{statistics.fmean(values):.3f}" if values else "-"


def table(headers: list[str], rows: list[list]) -> str:
    head = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in row) + "</tr>" for row in rows)
    return f"<div class='scroll'><table><tr>{head}</tr>{body}</table></div>"


def read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open(encoding="utf-8"))) if path.exists() else []


def combos(records: list[dict]) -> list[tuple[str, str]]:
    found = {(r["model"], r["variant"]) for r in records if r["kind"] == "scene"}
    return [(m, v) for m in sorted({m for m, _ in found}) for v in VARIANTS if (m, v) in found]


def build(out: Path) -> str:
    records = [json.loads(line) for line in (out / "results.jsonl").read_text(encoding="utf-8").splitlines() if line]
    scores, returns = read_csv(out / "scores.csv"), read_csv(out / "returns.csv")
    pairs = combos(records)
    parts = ["<h1>Spójność obrazów</h1>",
             ("<p>Podobieństwo to cosinus embeddingów DINOv2 (wygląd), wyżej = bardziej podobne. "
              "Postacie są porównywane na wycinkach z detektora osób, nie na całych obrazach.</p>")]

    # Czas i pamięć
    rows = []
    for m, v in pairs:
        scenes = [r.get("seconds_total", r["seconds"]) for r in records
                  if r["model"] == m and r.get("variant") == v and r["kind"] == "scene"]
        vram = [r.get("vram_peak_gb") or 0 for r in records if r["model"] == m]
        rows.append([m, VARIANT_NAMES[v], len(scenes), f"{statistics.median(scenes):.1f}", f"{max(vram):.1f}"])
    parts += ["<h2>Czas i pamięć</h2>",
              "<p>Czas sceny w wariancie warstwy = obrazy postaci + składanie (tło z cache).</p>",
              table(["model", "wariant", "sceny", "mediana s/scena", "szczyt VRAM GB"], rows)]

    if not scores:
        parts.append("<p>Brak scores.csv: uruchom score.py, żeby zobaczyć oceny.</p>")
    else:
        chars = [s for s in scores if s["entity_kind"] == "character"]
        # Powroty: najważniejsza tabela
        if returns:
            rows = []
            for m, v in pairs:
                mine = [r for r in returns if r["model"] == m and r["variant"] == v]
                people = [num(r["dino"]) for r in mine if r["entity"] != "(cała scena)"]
                scene = [num(r["dino"]) for r in mine if r["entity"] == "(cała scena)"]
                found = [int(r["both_detected"]) for r in mine if r["entity"] != "(cała scena)"]
                rows.append([m, VARIANT_NAMES[v], mean(people), mean(scene),
                             f"{sum(found)}/{len(found)}" if found else "-"])
            rows.sort(key=lambda r: r[2], reverse=True)
            parts += ["<h2>Powrót w to samo miejsce: runda późniejsza kontra pierwsza wizyta</h2>",
                      ("<p>Pary scen 20/1, 19/3, 17/5, 15/2, 14/4 (to samo miejsce, postacie i akcja). "
                       "Posortowane od najbardziej spójnych postaci.</p>"),
                      table(["model", "wariant", "postacie (dino)", "cała scena (dino)", "postacie znalezione"], rows)]
        # Rozjeżdżanie się w czasie
        rows = []
        for m, v in pairs:
            mine = [s for s in chars if s["model"] == m and s["variant"] == v]
            cells = [mean(num(s["dino_first"]) for s in mine if lo <= int(s["k"]) <= hi) for lo, hi in K_BUCKETS]
            found = [int(s["detected"]) for s in mine]
            rows.append([m, VARIANT_NAMES[v], *cells, f"{100 * sum(found) / len(found):.0f}%" if found else "-"])
        parts += ["<h2>Postać w kolejnych rundach: podobieństwo do pierwszego pojawienia się</h2>",
                  "<p>k = które pojawienie się postaci (Aren jest w każdej scenie, więc k dochodzi do 22).</p>",
                  table(["model", "wariant", *[f"k {lo} do {hi}" for lo, hi in K_BUCKETS], "postać znaleziona"], rows)]
        # Zgodność ze wzorcem i z opisem
        rows = []
        for m, v in pairs:
            mine = [s for s in scores if s["model"] == m and s["variant"] == v]
            rows.append([m, VARIANT_NAMES[v],
                         mean(num(s["dino_anchor"]) for s in mine if s["entity_kind"] == "character"),
                         mean(num(s["dino_anchor"]) for s in mine if s["entity_kind"] == "location"),
                         mean(num(s["clipscore"]) for s in mine if s["entity_kind"] == "location")])
        parts += ["<h2>Zgodność ze wzorcem i z opisem sceny</h2>",
                  table(["model", "wariant", "postać vs wzorzec", "scena vs wzorzec lokacji", "clipscore"], rows)]

    # Runda 1 kontra runda 20 obok siebie
    scene_by = {(r["model"], r["seed"], r["variant"], r["scene"]): r for r in records if r["kind"] == "scene"}
    returns_of = sorted({(r["scene"], r["return_of"]) for r in records if r["kind"] == "scene" and r.get("return_of")},
                        reverse=True)
    if returns_of:
        late, early = returns_of[0]
        parts.append(f"<h2>Runda {early} i runda {late} obok siebie (pierwszy seed)</h2>")
        for m in sorted({m for m, _ in pairs}):
            seed = min(r["seed"] for r in records if r["model"] == m)
            figs = []
            for v in VARIANTS:
                a, b = scene_by.get((m, seed, v, early)), scene_by.get((m, seed, v, late))
                if a and b:
                    figs.append(figure(a, f"{VARIANT_NAMES[v]}: runda {early}"))
                    figs.append(figure(b, f"{VARIANT_NAMES[v]}: runda {late}"))
            parts.append(f"<h3>{html.escape(m)}</h3><div class='row pairs'>{''.join(figs)}</div>")

    # Wszystkie obrazy (pierwszy seed)
    parts.append("<h2>Wszystkie obrazy (pierwszy seed)</h2>")
    for m in sorted({r["model"] for r in records}):
        seed = min(r["seed"] for r in records if r["model"] == m)
        mine = [r for r in records if r["model"] == m and r["seed"] == seed]
        parts.append(f"<h3>{html.escape(m)}, seed {seed}</h3>")
        anchors = [r for r in mine if r["kind"] == "anchor"]
        parts.append(f"<h4>wzorce</h4><div class='row'>{''.join(figure(r, r['entity']) for r in anchors)}</div>")
        for v in VARIANTS:
            scenes = sorted((r for r in mine if r.get("variant") == v and r["kind"] == "scene"), key=lambda r: r["scene"])
            if scenes:
                figs = "".join(figure(r, f"{r['scene']}: {r['location']}, {', '.join(r['characters'])}"
                                      + (f" (powrót do {r['return_of']})" if r.get("return_of") else ""))
                               for r in scenes)
                parts.append(f"<h4>{VARIANT_NAMES[v]}</h4><div class='row'>{figs}</div>")
    style = ("body{font-family:sans-serif;margin:24px;max-width:1400px}table{border-collapse:collapse;margin:8px 0}"
             "td,th{border:1px solid #ccc;padding:4px 8px;text-align:left}.scroll{overflow-x:auto}"
             ".row{display:flex;gap:6px;overflow-x:auto;padding-bottom:6px}.pairs{flex-wrap:wrap}"
             "figure{margin:0;font-size:12px;width:240px;flex:none}img{width:240px}")
    return f"<!doctype html><meta charset='utf-8'><title>Spójność obrazów</title><style>{style}</style>" + "".join(parts)


def figure(record: dict, caption: str) -> str:
    seconds = record.get("seconds_total", record["seconds"])
    return (f"<figure><img src='{html.escape(record['path'])}' loading='lazy'>"
            f"<figcaption>{html.escape(caption)} ({seconds} s)</figcaption></figure>")


def main() -> None:
    p = argparse.ArgumentParser(description="Raport HTML z wyników pomiaru spójności obrazów.")
    p.add_argument("--out", required=True)
    out = Path(p.parse_args().out).expanduser()
    (out / "report.html").write_text(build(out), encoding="utf-8")
    print(f"Zapisano {out / 'report.html'}")


if __name__ == "__main__":
    main()
