"""Adaptery modeli obrazów za wspólnym interfejsem.

Każdy adapter: load(), generate(prompt, refs, seed, out, size) -> dict z dodatkowymi danymi, unload().
refs to lista ścieżek do obrazów wejściowych (pusta = sam tekst).
torch i diffusers są importowane dopiero w load(), więc runner i testy działają bez nich.

UWAGA: FLUX.2 klein i FLUX 3 Image Klein to nowe modele. Parametry sprawdzone w dokumentacji diffusers
i na kartach modeli (2026-11-04), ale nie uruchomione na GPU: najpierw krótki test (README, krok 8).
"""

import gc
import os
from pathlib import Path

# Mniej marnowanej pamięci GPU przy obrazach różnej wielkości (ustawione przed pierwszym importem torch)
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")


class FakeAdapter:
    """Model na niby do testów: zapisuje mały plik zamiast obrazu."""

    name = "fake"
    max_refs = 10

    def __init__(self):
        self.calls: list[dict] = []

    def load(self) -> None:
        pass

    def generate(self, prompt: str, refs: list[Path], seed: int, out: Path, size: tuple[int, int]) -> dict:
        self.calls.append({"prompt": prompt, "refs": [str(r) for r in refs], "seed": seed, "out": str(out)})
        out.write_bytes(f"fake {seed} {prompt}".encode())
        return {"vram_peak_gb": 0.0}

    def unload(self) -> None:
        pass


class _Diffusers:
    """Wspólne części adapterów diffusers: GPU, seed, pomiar VRAM, zwalnianie pamięci."""

    name = ""
    max_refs = 0
    repo = ""
    ref_max_side: int | None = None  # zmniejszanie obrazów wejściowych (mniej pamięci GPU), None = bez zmian

    def __init__(self, repo: str | None = None):
        self.repo = repo or self.repo
        self.pipe = None

    def load(self) -> None:
        import torch

        self.torch = torch
        self.pipe = self._load(torch)
        if hasattr(self.pipe, "set_progress_bar_config"):
            self.pipe.set_progress_bar_config(disable=True)

    def generate(self, prompt: str, refs: list[Path], seed: int, out: Path, size: tuple[int, int]) -> dict:
        from PIL import Image

        torch = self.torch
        torch.cuda.reset_peak_memory_stats()
        images = [Image.open(r).convert("RGB") for r in refs[: self.max_refs]]
        if self.ref_max_side:
            for im in images:
                im.thumbnail((self.ref_max_side, self.ref_max_side))
        generator = torch.Generator("cpu").manual_seed(seed)
        image = self._generate(prompt, images, generator, size)
        torch.cuda.synchronize()
        image.save(out)
        return {"vram_peak_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2), "refs_used": len(images)}

    def unload(self) -> None:
        self.pipe = None
        gc.collect()
        if hasattr(self, "torch"):
            self.torch.cuda.empty_cache()

    def _load(self, torch): ...

    def _generate(self, prompt, images, generator, size): ...


class SDXLIPAdapter(_Diffusers):
    """SDXL z IP-Adapterem: obrazy wejściowe jako dodatkowy warunek. Punkt odniesienia."""

    name = "sdxl-ip"
    max_refs = 4
    repo = "stabilityai/stable-diffusion-xl-base-1.0"
    scale = 0.6  # siła obrazu wejściowego (0 = sam tekst)

    def _load(self, torch):
        from diffusers import AutoencoderKL, StableDiffusionXLPipeline

        vae = AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=torch.float16)
        pipe = StableDiffusionXLPipeline.from_pretrained(self.repo, vae=vae, torch_dtype=torch.float16,
                                                         variant="fp16")
        pipe.load_ip_adapter("h94/IP-Adapter", subfolder="sdxl_models", weight_name="ip-adapter_sdxl.bin")
        return pipe.to("cuda")

    def _generate(self, prompt, images, generator, size):
        from PIL import Image

        # Załadowany IP-Adapter wymaga obrazu, więc bez obrazów: szary obraz i siła 0 (czyli sam tekst)
        self.pipe.set_ip_adapter_scale(self.scale if images else 0.0)
        refs = images or [Image.new("RGB", (224, 224), (128, 128, 128))]
        return self.pipe(prompt=prompt, ip_adapter_image=[refs], width=size[0], height=size[1],
                         num_inference_steps=30, guidance_scale=6.0, generator=generator).images[0]


class Flux2Klein(_Diffusers):
    """FLUX.2 [klein] 4B: destylowany, 4 kroki, edycja z wieloma obrazami, Apache 2.0, ok. 13 GB VRAM."""

    name = "flux2-klein-4b"
    max_refs = 4
    repo = "black-forest-labs/FLUX.2-klein-4B"

    def _load(self, torch):
        from diffusers import Flux2KleinPipeline

        return Flux2KleinPipeline.from_pretrained(self.repo, torch_dtype=torch.bfloat16).to("cuda")

    def _generate(self, prompt, images, generator, size):
        kwargs = {"image": images} if images else {}
        return self.pipe(prompt=prompt, width=size[0], height=size[1], guidance_scale=1.0,
                         num_inference_steps=4, generator=generator, **kwargs).images[0]


class Flux3Klein(_Diffusers):
    """FLUX 3 Image Klein: 5,6B, do 10 obrazów wejściowych, licencja FLUX Kommunity (gated na HF).

    Wersja destylowana (karta modelu, 2026-11-04): 16 kroków bez guidance, VAE w float32.
    Bez „prompt upsamplera” (osobny model 9B, ok. 19 GB do pobrania i ok. 28 GB VRAM): nasze prompty to już pełne
    opisy sceny, a karta modelu podaje usunięcie tego bloku jako sposób na wyłączenie.
    Pełna precyzja zajmuje ok. 31 GB (pomiar producenta), więcej niż 24 GB RTX 4090, dlatego automatyczne
    odciążanie do RAM (ComponentsManager): modele trafiają na GPU tylko na czas swojego kroku.
    """

    name = "flux3-klein"
    max_refs = 10
    repo = "black-forest-labs/flux-3-image-klein"

    def _load(self, torch):
        from diffusers import ComponentsManager, ModularPipeline

        manager = ComponentsManager()
        manager.enable_auto_cpu_offload(device="cuda")
        blocks = ModularPipeline.from_pretrained(self.repo).blocks
        blocks.sub_blocks.pop("prompt_upsampler")
        pipe = blocks.init_pipeline(self.repo, components_manager=manager)
        pipe.load_components(dtype={"vae": torch.float32, "default": torch.bfloat16})
        return pipe

    def _generate(self, prompt, images, generator, size):
        kwargs = {"image": images} if images else {}
        return self.pipe(prompt=prompt, width=size[0], height=size[1], num_inference_steps=16,
                         generator=generator, output="images", **kwargs)[0]


class Qwen21Turbo(_Diffusers):
    """Qwen-Image-2.1-Turbo: 7B, 8 kroków (harmonogram zapisany w modelu), do 10 obrazów wejściowych,
    zachowanie tożsamości osób, Qwen Research License (badania). Rozmiar w VRAM bez odciążania nie jest podany
    na karcie modelu, a razem z koderem tekstu przekracza 24 GB, dlatego odciążanie do RAM (części modelu
    trafiają na GPU tylko na czas swojego kroku). Model trenowany na ok. 2K, my generujemy 1280x720.
    """

    name = "qwen-image-21-turbo"
    max_refs = 10
    repo = "Qwen/Qwen-Image-2.1-Turbo"
    # Pełnowymiarowe obrazy wejściowe (3 x 1280x720) przekroczyły 24 GB przy wariancie anchor (2026-11-05)
    ref_max_side = 768

    def _load(self, torch):
        from diffusers import QwenImage21Pipeline

        pipe = QwenImage21Pipeline.from_pretrained(self.repo, torch_dtype=torch.bfloat16)
        pipe.enable_model_cpu_offload()
        return pipe

    def _generate(self, prompt, images, generator, size):
        # Liczby kroków nie podajemy: Turbo ma zapisany harmonogram 8 kroków (karta modelu)
        kwargs = {"image": images} if images else {}
        return self.pipe(prompt=prompt, width=size[0], height=size[1], generator=generator, **kwargs).images[0]


ADAPTERS = {cls.name: cls for cls in (SDXLIPAdapter, Flux2Klein, Flux3Klein, Qwen21Turbo)}


def make_adapter(name: str, repo: str | None = None):
    if name == "fake":
        return FakeAdapter()
    if name not in ADAPTERS:
        raise SystemExit(f"Nieznany model {name}. Dostępne: {', '.join(ADAPTERS)}")
    return ADAPTERS[name](repo)
