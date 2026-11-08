"""Oceny spójności dla wyników run.py. Mierzymy postacie na wycinkach, a nie całe obrazy.

1. Detektor osób (OWLv2, zapytanie „a person”) znajduje postacie na każdym obrazie sceny i na wzorcach postaci.
2. Wycinki dopasowujemy do postaci ze sceny (najwyższa suma podobieństw do ich wzorców). Zapis: crops/.
3. Dla każdej postaci w scenie (scores.csv):
     dino_anchor, clip_anchor  podobieństwo wycinka do wycinka ze wzorca postaci
     dino_first, clip_first    podobieństwo do wycinka z pierwszego pojawienia się postaci w tym wariancie (k = 1)
     detected                  czy postać w ogóle znaleziono (zniknięcie postaci to też błąd spójności)
   Dla lokacji: podobieństwo całej sceny do wzorca lokacji. Dla sceny: clipscore = 100 × max(cos(obraz, opis), 0).
4. Powroty (returns.csv): scena z return_of kontra jej pierwsza wizyta: postacie (wycinki) i cała scena.

Podobieństwo = cosinus embeddingów DINOv2 (wygląd) i CLIP (treść), wyżej = bardziej podobne.

  python score.py --out ~/data/dvn-results/consistency
"""

import argparse
import csv
import itertools
import json
from pathlib import Path

DINO = "facebook/dinov2-base"
CLIP = "openai/clip-vit-large-patch14"
DETECTOR = "google/owlv2-base-patch16-ensemble"


# --- Czyste funkcje (bez torch, testowane w kontenerze gry) ---

def iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def nms(boxes: list[tuple[float, list[float]]], threshold: float = 0.5, limit: int = 6) -> list[list[float]]:
    """Wybiera najpewniejsze ramki (score, box), pomija nakładające się."""
    kept: list[list[float]] = []
    for _, box in sorted(boxes, key=lambda x: -x[0]):
        if all(iou(box, k) < threshold for k in kept):
            kept.append(box)
        if len(kept) == limit:
            break
    return kept


def assign(sim: list[list[float]]) -> dict[int, int]:
    """sim[postać][wycinek] -> {postać: wycinek} z najwyższą sumą podobieństw (postaci jest najwyżej kilka).
    Gdy wycinków jest mniej niż postaci, część postaci zostaje bez wycinka (nie znaleziona)."""
    n_chars, n_crops = len(sim), len(sim[0]) if sim else 0
    best, best_score = {}, float("-inf")
    for chars in itertools.permutations(range(n_chars), min(n_chars, n_crops)):
        for crops in itertools.permutations(range(n_crops), len(chars)):
            score = sum(sim[c][k] for c, k in zip(chars, crops, strict=True))
            if score > best_score:
                best, best_score = dict(zip(chars, crops, strict=True)), score
    return best


# --- Modele ---

def main() -> None:
    p = argparse.ArgumentParser(description="Oceny spójności postaci (wycinki) i lokacji dla wyników run.py.")
    p.add_argument("--out", required=True)
    # 0.1, bo przy 0.15 detektor gubił postacie na obrazach Qwena (mediana najlepszego wyniku ok. 0.14, FLUX i SDXL ok. 0.27)
    p.add_argument("--threshold", type=float, default=0.1, help="próg pewności detektora osób")
    args = p.parse_args()
    out = Path(args.out).expanduser()

    import torch
    from PIL import Image
    from transformers import (
        AutoImageProcessor,
        AutoModel,
        CLIPModel,
        CLIPProcessor,
        Owlv2ForObjectDetection,
        Owlv2Processor,
    )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dino_proc, dino = AutoImageProcessor.from_pretrained(DINO), AutoModel.from_pretrained(DINO).to(device).eval()
    clip_proc, clip = CLIPProcessor.from_pretrained(CLIP), CLIPModel.from_pretrained(CLIP).to(device).eval()
    det_proc = Owlv2Processor.from_pretrained(DETECTOR)
    det = Owlv2ForObjectDetection.from_pretrained(DETECTOR).to(device).eval()
    norm = torch.nn.functional.normalize

    @torch.no_grad()
    def embed(image) -> tuple:
        d = dino(**dino_proc(images=image, return_tensors="pt").to(device)).pooler_output[0]
        # Wprost przez model wizji i projekcję: get_image_features zwraca co innego w transformers 4 i 5
        pixels = clip_proc(images=image, return_tensors="pt").to(device)["pixel_values"]
        c = clip.visual_projection(clip.vision_model(pixel_values=pixels).pooler_output)[0]
        return norm(d, dim=0), norm(c, dim=0)

    @torch.no_grad()
    def text_embed(text: str):
        t = clip_proc(text=[text], return_tensors="pt", truncation=True, max_length=77).to(device)
        pooled = clip.text_model(input_ids=t["input_ids"], attention_mask=t["attention_mask"]).pooler_output
        return norm(clip.text_projection(pooled)[0], dim=0)

    @torch.no_grad()
    def people(image, limit: int) -> list[list[float]]:
        inputs = det_proc(text=[["a person"]], images=image, return_tensors="pt").to(device)
        outputs = det(**inputs)
        side = max(image.size)  # OWLv2 dopełnia obraz do kwadratu, ramki są w układzie tego kwadratu
        sizes = torch.tensor([[side, side]]).to(device)
        if hasattr(det_proc, "post_process_grounded_object_detection"):  # transformers 5
            res = det_proc.post_process_grounded_object_detection(outputs, threshold=args.threshold,
                                                                  target_sizes=sizes)[0]
        else:
            res = det_proc.post_process_object_detection(outputs, threshold=args.threshold, target_sizes=sizes)[0]
        w, h = image.size
        boxes = []
        for s, b in zip(res["scores"], res["boxes"], strict=True):
            x0, y0, x1, y1 = (float(v) for v in b)
            box = [max(0.0, x0), max(0.0, y0), min(float(w), x1), min(float(h), y1)]
            if box[2] - box[0] > 8 and box[3] - box[1] > 8:
                boxes.append((float(s), box))
        return nms(boxes, limit=limit)

    def sim(a, b) -> tuple[float, float]:
        return round(float(a[0] @ b[0]), 4), round(float(a[1] @ b[1]), 4)

    records = [json.loads(line) for line in (out / "results.jsonl").read_text(encoding="utf-8").splitlines() if line]
    crops_dir = out / "crops"
    whole: dict[str, tuple] = {}
    crop_emb: dict[tuple[str, str], tuple] = {}  # (ścieżka obrazu, postać) -> embedding wycinka

    def image_of(rel: str):
        return Image.open(out / rel).convert("RGB")

    def whole_emb(rel: str):
        if rel not in whole:
            whole[rel] = embed(image_of(rel))
        return whole[rel]

    def save_crop(image, box, rel: str, who: str):
        path = crops_dir / Path(rel).with_suffix("") / f"{who}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        image.crop(tuple(round(v) for v in box)).save(path)

    # Wzorce postaci: największa wykryta osoba (albo cały obraz, gdy detektor nic nie znajdzie)
    anchor_crop: dict[tuple, tuple] = {}
    for r in records:
        if r["kind"] == "anchor" and r["entity_kind"] == "character":
            image = image_of(r["path"])
            boxes = people(image, limit=3)
            box = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])) if boxes else [0, 0, *image.size]
            save_crop(image, box, r["path"], r["entity"])
            anchor_crop[(r["model"], r["seed"], r["entity"])] = embed(image.crop(tuple(round(v) for v in box)))
    loc_anchor = {(r["model"], r["seed"], r["entity"]): r["path"] for r in records
                  if r["kind"] == "anchor" and r["entity_kind"] == "location"}

    scenes = sorted((r for r in records if r["kind"] == "scene"),
                    key=lambda r: (r["model"], r["seed"], r["variant"], r["scene"]))
    for r in scenes:
        image = image_of(r["path"])
        chars = r["characters"]
        boxes = people(image, limit=len(chars) + 2)
        embs = [embed(image.crop(tuple(round(v) for v in b))) for b in boxes]
        refs = [anchor_crop.get((r["model"], r["seed"], c)) for c in chars]
        matrix = [[float(ref[0] @ e[0]) if ref else 0.0 for e in embs] for ref in refs]
        for ci, ki in assign(matrix).items():
            crop_emb[(r["path"], chars[ci])] = embs[ki]
            save_crop(image, boxes[ki], r["path"], chars[ci])

    first: dict[tuple, str] = {}  # (model, seed, wariant, postać) -> ścieżka sceny z k = 1
    for r in scenes:
        for c in r["characters"]:
            if r["k"][c] == 1:
                first[(r["model"], r["seed"], r["variant"], c)] = r["path"]

    rows, returns = [], []
    by_scene = {(r["model"], r["seed"], r["variant"], r["scene"]): r for r in scenes}
    for r in scenes:
        clipscore = round(100 * max(float(whole_emb(r["path"])[1] @ text_embed(r["prompt"])), 0.0), 2)
        seconds = r.get("seconds_total", r["seconds"])
        base = {"model": r["model"], "variant": r["variant"], "seed": r["seed"], "scene": r["scene"],
                "clipscore": clipscore, "seconds": seconds, "vram_peak_gb": r.get("vram_peak_gb")}
        for c in r["characters"]:
            emb = crop_emb.get((r["path"], c))
            anchor = anchor_crop.get((r["model"], r["seed"], c))
            ref_first = crop_emb.get((first.get((r["model"], r["seed"], r["variant"], c)), c))
            da, ca = sim(emb, anchor) if emb and anchor else ("", "")
            df, cf = sim(emb, ref_first) if emb and ref_first and r["k"][c] > 1 else ("", "")
            rows.append({**base, "entity": c, "entity_kind": "character", "k": r["k"][c], "detected": int(bool(emb)),
                         "dino_anchor": da, "clip_anchor": ca, "dino_first": df, "clip_first": cf})
        loc = r["location"]
        da, ca = sim(whole_emb(r["path"]), whole_emb(loc_anchor[(r["model"], r["seed"], loc)]))
        rows.append({**base, "entity": loc, "entity_kind": "location", "k": r["k"][loc], "detected": 1,
                     "dino_anchor": da, "clip_anchor": ca, "dino_first": "", "clip_first": ""})
        if r.get("return_of"):
            orig = by_scene.get((r["model"], r["seed"], r["variant"], r["return_of"]))
            if orig:
                dw, cw = sim(whole_emb(r["path"]), whole_emb(orig["path"]))
                for c in ["(cała scena)", *r["characters"]]:
                    if c == "(cała scena)":
                        d, cl, found = dw, cw, 1
                    else:
                        a, b = crop_emb.get((r["path"], c)), crop_emb.get((orig["path"], c))
                        d, cl = sim(a, b) if a and b else ("", "")
                        found = int(bool(a and b))
                    returns.append({"model": r["model"], "variant": r["variant"], "seed": r["seed"],
                                    "scene": r["scene"], "return_of": r["return_of"], "entity": c,
                                    "both_detected": found, "dino": d, "clip": cl,
                                    "path": r["path"], "orig_path": orig["path"]})

    for name, data in (("scores.csv", rows), ("returns.csv", returns)):
        if data:
            with (out / name).open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(data[0]))
                writer.writeheader()
                writer.writerows(data)
    print(f"Zapisano {len(rows)} ocen (scores.csv), {len(returns)} porównań powrotów (returns.csv), wycinki w {crops_dir}.")
    print(f"Raport: python report.py --out {out}")


if __name__ == "__main__":
    main()
