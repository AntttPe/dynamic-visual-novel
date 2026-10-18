#!/usr/bin/env bash
# Benchmark na podzie z GPU (np. RunPod, szablon PyTorch, karta A40 48 GB).
# Użycie: bash run.sh --models sd15 sdxl-turbo sdxl flux-schnell --runs 3 --gpu-price 0.35
set -euo pipefail
cd "$(dirname "$0")"

# Modele zapisują się na dysku sieciowym, więc po restarcie poda nie trzeba ich pobierać ponownie
export HF_HOME="${HF_HOME:-/workspace/hf-cache}"

if [ -z "${HF_TOKEN:-}" ]; then
  echo "Uwaga: brak HF_TOKEN. FLUX.1-schnell się nie pobierze (pozostałe modele tak)."
fi

pip install -q -r requirements.txt
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
python bench_images.py "$@"
