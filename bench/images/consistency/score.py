"""Oceny spójności dla wyników run.py: podobieństwo sceny do obrazów wzorcowych i zgodność z opisem.

Dla każdej sceny i każdej postaci lub lokacji w niej:
  dino   cosinus embeddingów DINOv2 sceny i obrazu wzorcowego (podobieństwo wizualne)
  clip   cosinus embeddingów obrazów CLIP sceny i wzorca
Dla każdej sceny: clipscore = 100 × max(cos(obraz, opis sceny), 0).

Ograniczenie: porównujemy cały obraz sceny z całym wzorcem, więc podobieństwo postaci miesza się z tłem.
Dokładniejsza ocena postaci: sędzia obrazów (zadanie Z5) albo wycinanie postaci.
Wymaga GPU albo cierpliwości (na CPU działa, ale wolno).

  python score.py --out ~/data/dvn/consistency
"""

import argparse
import csv
import json
from pathlib import Path

DINO = "facebook/dinov2-base"
CLIP = "openai/clip-vit-large-patch14"


def main() -> None:
    p = argparse.ArgumentParser(description="Oceny DINOv2 i CLIP dla wyników run.py.")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    out = Path(args.out).expanduser()

    import torch
    from PIL import Image
    from transformers import AutoImageProcessor, AutoModel, CLIPModel, CLIPProcessor

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dino_proc, dino = AutoImageProcessor.from_pretrained(DINO), AutoModel.from_pretrained(DINO).to(device).eval()
    clip_proc, clip = CLIPProcessor.from_pretrained(CLIP), CLIPModel.from_pretrained(CLIP).to(device).eval()
    cache: dict[str, tuple] = {}

    @torch.no_grad()
    def embed(rel: str):
        if rel not in cache:
            image = Image.open(out / rel).convert("RGB")
            d = dino(**dino_proc(images=image, return_tensors="pt").to(device)).pooler_output[0]
            c = clip.get_image_features(**clip_proc(images=image, return_tensors="pt").to(device))[0]
            cache[rel] = (torch.nn.functional.normalize(d, dim=0), torch.nn.functional.normalize(c, dim=0))
        return cache[rel]

    @torch.no_grad()
    def text_embed(text: str):
        t = clip_proc(text=[text], return_tensors="pt", truncation=True, max_length=77).to(device)
        return torch.nn.functional.normalize(clip.get_text_features(**t)[0], dim=0)

    records = [json.loads(line) for line in (out / "results.jsonl").read_text(encoding="utf-8").splitlines() if line]
    anchors = {(r["model"], r["seed"], r["entity"]): r["path"] for r in records if r["kind"] == "anchor"}
    rows = []
    for r in records:
        if r["kind"] != "scene":
            continue
        dino_s, clip_s = embed(r["path"])
        clipscore = round(100 * max(float(clip_s @ text_embed(r["prompt"])), 0.0), 2)
        for entity, k in r["k"].items():
            ref = anchors.get((r["model"], r["seed"], entity))
            if ref is None:
                continue
            dino_a, clip_a = embed(ref)
            rows.append({
                "model": r["model"], "variant": r["variant"], "seed": r["seed"], "scene": r["scene"],
                "entity": entity, "entity_kind": "location" if entity == r["location"] else "character", "k": k,
                "dino": round(float(dino_s @ dino_a), 4), "clip": round(float(clip_s @ clip_a), 4),
                "clipscore": clipscore, "seconds": r["seconds"], "vram_peak_gb": r.get("vram_peak_gb"),
            })
    with (out / "scores.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Zapisano {len(rows)} ocen do {out / 'scores.csv'}. Raport: python report.py --out {out}")


if __name__ == "__main__":
    main()
