"""Benchmark modeli obrazów: czas generowania, pamięć GPU i koszt tła na wynajętym GPU.

Uruchamiany osobno od gry (na maszynie z GPU), bo wymaga torch i diffusers.

  python bench_images.py --models sd15 sdxl-turbo sdxl flux-schnell --runs 3 --gpu-price 0.35
  python bench_images.py --dry-run          # bez GPU: sprawdza tylko zapis wyników i raportu
"""

import argparse
import csv
import gc
import html
import json
import platform
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Stały prefiks stylu, jak w docelowej grze. Prompty po angielsku, bo tak trenowano kodery tekstu.
STYLE = "visual novel background art, painterly digital illustration, soft cinematic lighting, no people, no text"
NEGATIVE = "people, characters, text, watermark, blurry, low quality"


@dataclass(frozen=True)
class ModelSpec:
    key: str
    repo: str
    family: str  # sd, sdxl, flux
    width: int
    height: int
    steps: int
    guidance: float
    dtype: str  # fp16 albo bf16
    note: str


MODELS = {
    "sd15": ModelSpec("sd15", "stable-diffusion-v1-5/stable-diffusion-v1-5", "sd",
                      768, 432, 25, 7.0, "fp16", "stary i lekki, słabsza jakość"),
    "sdxl-turbo": ModelSpec("sdxl-turbo", "stabilityai/sdxl-turbo", "sdxl",
                            768, 432, 4, 0.0, "fp16", "destylowany SDXL, 1 do 4 kroków, licencja niekomercyjna"),
    "sdxl": ModelSpec("sdxl", "stabilityai/stable-diffusion-xl-base-1.0", "sdxl",
                      1344, 768, 30, 6.0, "fp16", "dobra jakość, wolniejszy"),
    "flux-schnell": ModelSpec("flux-schnell", "black-forest-labs/FLUX.1-schnell", "flux",
                              1024, 576, 4, 0.0, "bf16", "Apache 2.0, 4 kroki, ok. 33 GB VRAM, wymaga HF_TOKEN"),
}


# ---------- GPU ----------

def pick_device(torch):
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def sync(torch, device):
    if device == "cuda":
        torch.cuda.synchronize()
    elif device == "mps":
        torch.mps.synchronize()


def is_cached(repo: str) -> bool:
    from huggingface_hub import try_to_load_from_cache
    return isinstance(try_to_load_from_cache(repo, "model_index.json"), str)


def load_pipeline(spec: ModelSpec, device: str):
    import torch
    from diffusers import AutoencoderKL, AutoPipelineForText2Image, FluxPipeline

    dtype = torch.float32 if device == "cpu" else (torch.bfloat16 if spec.dtype == "bf16" else torch.float16)
    kwargs = {"torch_dtype": dtype}
    if spec.family == "sd":
        kwargs |= {"safety_checker": None, "requires_safety_checker": False}
    if spec.key == "sdxl" and dtype == torch.float16:
        # oryginalny VAE SDXL w fp16 daje czarne obrazy
        kwargs["vae"] = AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=dtype)
    cls = FluxPipeline if spec.family == "flux" else AutoPipelineForText2Image
    try:
        pipe = cls.from_pretrained(spec.repo, variant="fp16" if spec.dtype == "fp16" else None, **kwargs)
    except (OSError, ValueError):
        pipe = cls.from_pretrained(spec.repo, **kwargs)  # repozytorium bez wariantu fp16
    pipe.to(device)
    pipe.set_progress_bar_config(disable=True)
    return pipe


def generate(pipe, spec: ModelSpec, prompt: str, seed: int, device: str, steps: int):
    import torch

    kwargs = {
        "prompt": prompt, "num_inference_steps": steps, "guidance_scale": spec.guidance,
        "width": spec.width, "height": spec.height,
        "generator": torch.Generator("cpu").manual_seed(seed),
    }
    if spec.family == "flux":
        kwargs["max_sequence_length"] = 256
    elif spec.guidance > 1:
        kwargs["negative_prompt"] = NEGATIVE
    sync(torch, device)
    t0 = time.perf_counter()
    image = pipe(**kwargs).images[0]
    sync(torch, device)
    return image, time.perf_counter() - t0


# ---------- statystyki ----------

def summarize(times: list[float], gpu_price: float) -> dict:
    s = sorted(times)
    median = statistics.median(s)
    p95 = s[min(len(s) - 1, round(0.95 * (len(s) - 1)))]
    return {
        "n": len(s), "mean_s": statistics.fmean(s), "median_s": median, "p95_s": p95,
        "min_s": s[0], "max_s": s[-1],
        "images_per_hour": 3600 / median,
        "cost_per_image_usd": gpu_price * median / 3600,
        "cost_per_1000_usd": gpu_price * median / 3600 * 1000,
    }


def bench_model(spec: ModelSpec, prompts: list[dict], args, out: Path) -> dict:
    import torch

    device = pick_device(torch)
    steps = args.steps or spec.steps
    cached = is_cached(spec.repo)
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    t0 = time.perf_counter()
    pipe = load_pipeline(spec, device)
    load_s = time.perf_counter() - t0

    _, warmup_s = generate(pipe, spec, f"{STYLE}, {prompts[0]['text']}", args.seed, device, steps)
    times, images = [], []
    (out / spec.key).mkdir(parents=True, exist_ok=True)
    for run in range(args.runs):
        for i, p in enumerate(prompts):
            img, dt = generate(pipe, spec, f"{STYLE}, {p['text']}", args.seed + i, device, steps)
            times.append(dt)
            if run == 0:
                rel = f"{spec.key}/{p['id']}.png"
                img.save(out / rel)
                images.append({"prompt_id": p["id"], "path": rel, "seconds": dt})
            print(f"  {spec.key} run {run + 1}/{args.runs} {p['id']}: {dt:.2f} s", flush=True)

    peak = torch.cuda.max_memory_allocated() / 1e9 if device == "cuda" else None
    del pipe
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    return {
        "model": spec.key, "spec": asdict(spec), "steps": steps, "device": device,
        "cached_before": cached, "load_s": load_s, "warmup_s": warmup_s,
        "peak_vram_gb": peak, "times_s": times, "images": images,
        **summarize(times, args.gpu_price),
    }


def fake_result(spec: ModelSpec, prompts: list[dict], args) -> dict:
    """Wynik na niby do sprawdzenia raportu bez GPU."""
    steps = args.steps or spec.steps
    base = steps * spec.width * spec.height / 1e6 * (0.25 if spec.family == "flux" else 0.12)
    times = [round(base * (1 + 0.03 * (i % 4)), 3) for i in range(args.runs * len(prompts))]
    return {
        "model": spec.key, "spec": asdict(spec), "steps": steps, "device": "dry-run",
        "cached_before": True, "load_s": 8.0, "warmup_s": base * 2, "peak_vram_gb": None,
        "times_s": times, "images": [], **summarize(times, args.gpu_price),
    }


# ---------- zapis wyników ----------

COLUMNS = ["model", "steps", "width", "height", "median_s", "p95_s", "mean_s", "load_s", "warmup_s",
           "peak_vram_gb", "images_per_hour", "cost_per_image_usd", "cost_per_1000_usd"]


def write_outputs(results: list[dict], meta: dict, prompts: list[dict], out: Path) -> None:
    (out / "results.json").write_text(json.dumps({"meta": meta, "results": results}, indent=2, ensure_ascii=False))
    with open(out / "results.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in results:
            row = {**r, "width": r["spec"]["width"], "height": r["spec"]["height"]}
            w.writerow([round(v, 5) if isinstance(v, float) else v for v in (row[c] for c in COLUMNS)])
    (out / "report.html").write_text(render_html(results, meta, prompts), encoding="utf-8")


def render_html(results: list[dict], meta: dict, prompts: list[dict]) -> str:
    e = html.escape
    f2 = lambda v, d=2: "brak" if v is None else f"{v:.{d}f}".replace(".", ",")
    rows = "".join(
        f"<tr><td><b>{e(r['model'])}</b><br><small>{e(r['spec']['note'])}</small></td>"
        f"<td>{r['steps']}</td><td>{r['spec']['width']}×{r['spec']['height']}</td>"
        f"<td><b>{f2(r['median_s'])} s</b></td><td>{f2(r['p95_s'])} s</td>"
        f"<td>{f2(r['load_s'], 1)} s{'' if r['cached_before'] else ' (z pobieraniem)'}</td>"
        f"<td>{f2(r['warmup_s'])} s</td><td>{f2(r['peak_vram_gb'], 1)} GB</td>"
        f"<td>{r['images_per_hour']:.0f}</td><td>{r['cost_per_image_usd']:.5f} $</td>"
        f"<td><b>{f2(r['cost_per_1000_usd'])} $</b></td></tr>"
        for r in results)
    grid_head = "".join(f"<th>{e(r['model'])}</th>" for r in results)
    grid_rows = ""
    for p in prompts:
        cells = ""
        for r in results:
            img = next((i for i in r["images"] if i["prompt_id"] == p["id"]), None)
            cells += (f"<td><img src='{e(img['path'])}' alt=''><small>{f2(img['seconds'])} s</small></td>"
                      if img else "<td><small>brak obrazu</small></td>")
        grid_rows += f"<tr><th>{e(p['id'])}<br><small>{e(p['text'])}</small></th>{cells}</tr>"
    return f"""<!doctype html><html lang="pl"><head><meta charset="utf-8"><title>Benchmark obrazów</title>
<style>
body{{font:15px/1.5 system-ui,sans-serif;margin:24px;color:#161b22;background:#f4f5f7}}
table{{border-collapse:collapse;background:#fff;margin:12px 0 28px}}
td,th{{border:1px solid #d5dbe2;padding:7px 10px;text-align:left;vertical-align:top}}
th{{background:#eef0f3;font-weight:600}} small{{color:#5e6875;display:block}}
img{{width:320px;display:block;border-radius:6px}} .meta{{color:#5e6875}}
</style></head><body>
<h1>Benchmark modeli obrazów</h1>
<p class="meta">GPU: {e(str(meta['gpu']))} · cena {f2(meta['gpu_price'])} $/h · powtórzenia: {meta['runs']} · promptów: {len(prompts)} · {e(meta['date'])}{' · DRY-RUN, liczby nieprawdziwe' if meta['dry_run'] else ''}</p>
<p class="meta">Koszt = cena GPU za godzinę × mediana czasu jednego obrazu. Nie obejmuje czasu ładowania modelu ani bezczynności poda.
Dla porównania: FLUX.1-schnell przez API (Replicate, fal) to około 0,003 $ za obraz, czyli około 3 $ za 1000.</p>
<table><tr><th>Model</th><th>Kroki</th><th>Rozmiar</th><th>Mediana</th><th>p95</th><th>Ładowanie</th><th>1. obraz</th><th>VRAM (szczyt)</th><th>Obrazów/h</th><th>Koszt/obraz</th><th>Koszt/1000</th></tr>{rows}</table>
<h2>Obrazy (ten sam prompt i seed)</h2>
<table><tr><th>Prompt</th>{grid_head}</tr>{grid_rows}</table>
</body></html>"""


# ---------- main ----------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", default=list(MODELS), choices=list(MODELS))
    ap.add_argument("--runs", type=int, default=3, help="ile razy powtórzyć każdy prompt")
    ap.add_argument("--steps", type=int, default=None, help="nadpisuje domyślną liczbę kroków")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--gpu-price", type=float, default=0.35, help="cena GPU w $/h (A40 na RunPod: 0.35)")
    ap.add_argument("--prompts", type=Path, default=HERE / "prompts.json")
    ap.add_argument("--out", type=Path, default=HERE / "out")
    ap.add_argument("--dry-run", action="store_true", help="bez GPU, wyniki na niby")
    args = ap.parse_args()

    prompts = json.loads(args.prompts.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    gpu = "dry-run"
    if not args.dry_run:
        import torch
        gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else pick_device(torch)
    meta = {"gpu": gpu, "gpu_price": args.gpu_price, "runs": args.runs, "seed": args.seed,
            "dry_run": args.dry_run, "python": platform.python_version(),
            "date": datetime.now(UTC).isoformat(timespec="seconds")}

    results = []
    for key in args.models:
        spec = MODELS[key]
        print(f"== {key} ({spec.repo})", flush=True)
        try:
            results.append(fake_result(spec, prompts, args) if args.dry_run else bench_model(spec, prompts, args, args.out))
        except Exception as ex:  # noqa: BLE001  jeden model nie może zatrzymać całego testu
            print(f"  BŁĄD {key}: {type(ex).__name__}: {ex}", flush=True)
            continue
        write_outputs(results, meta, prompts, args.out)  # zapis po każdym modelu
        r = results[-1]
        print(f"  mediana {r['median_s']:.2f} s · {r['cost_per_1000_usd']:.2f} $/1000 obrazów", flush=True)
    print(f"Raport: {args.out / 'report.html'}")


if __name__ == "__main__":
    main()
