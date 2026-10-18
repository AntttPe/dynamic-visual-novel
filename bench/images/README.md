# Benchmark modeli obrazów

Mierzy, ile trwa wygenerowanie jednego tła i ile to kosztuje na wynajętym GPU.
Skrypt działa osobno od gry: wymaga karty graficznej oraz bibliotek `torch` i `diffusers`,
których nie ma w kontenerze gry.

## Co jest mierzone

| Wynik | Znaczenie |
|---|---|
| Mediana, p95 | czas jednego obrazu (bez ładowania modelu) |
| Ładowanie | wczytanie modelu na kartę; przy pierwszym uruchomieniu także pobieranie |
| 1. obraz | pierwsze generowanie jest wolniejsze, dlatego liczymy je osobno |
| VRAM (szczyt) | ile pamięci karty zajął model |
| Koszt/1000 | cena GPU za godzinę × mediana czasu × 1000 |

Każdy model rysuje te same 5 scen z tym samym seedem i stałym prefiksem stylu,
więc obrazy można porównać obok siebie w `out/report.html`.

| Model | Kroki | Rozmiar | Uwagi |
|---|---|---|---|
| `sd15` | 25 | 768×432 | stary i lekki |
| `sdxl-turbo` | 4 | 768×432 | bardzo szybki, licencja niekomercyjna |
| `sdxl` | 30 | 1344×768 | dobra jakość, wolniejszy |
| `flux-schnell` | 4 | 1024×576 | Apache 2.0, ok. 33 GB VRAM |

## Krok po kroku (RunPod)

1. **Hugging Face:** zaloguj się, wejdź na stronę
   [FLUX.1-schnell](https://huggingface.co/black-forest-labs/FLUX.1-schnell) i zaakceptuj warunki.
   W ustawieniach konta utwórz token typu *Read*. Bez tokenu pozostałe modele i tak zadziałają.
2. **RunPod:** uruchom poda z kartą A40 (48 GB), szablon *RunPod PyTorch*,
   dysk sieciowy (network volume) około 100 GB podpięty jako `/workspace`.
   Modele zajmą razem około 60 GB.
3. **Skopiuj skrypt** na poda (adres i port SSH są w panelu RunPod, w „Connect”):
   ```bash
   scp -P <port> -r bench/images root@<adres>:/workspace/
   ```
4. **Uruchom** na podzie:
   ```bash
   ssh -p <port> root@<adres>
   cd /workspace/images
   export HF_TOKEN=<twój-token>      # nie zapisuj go w repo
   bash run.sh --models sd15 sdxl-turbo sdxl flux-schnell --runs 3 --gpu-price 0.35
   ```
5. **Pobierz wyniki** na komputer i otwórz `report.html`:
   ```bash
   scp -P <port> -r root@<adres>:/workspace/images/out ./wyniki-obrazy
   ```
6. **Zatrzymaj poda.** Płacisz za każdą godzinę, kiedy jest włączony.

Pierwsze uruchomienie trwa najdłużej przez pobieranie modeli (zwykle kilkanaście minut).
Sam test to kilka minut. Całość powinna zmieścić się w około godzinie, czyli około 0,35 $.

## Przydatne opcje

| Opcja | Działanie |
|---|---|
| `--models sdxl-turbo flux-schnell` | tylko wybrane modele |
| `--runs 5` | więcej powtórzeń, dokładniejsza mediana |
| `--steps 2` | inna liczba kroków (np. sprawdzenie, czy FLUX daje radę w 2 krokach) |
| `--gpu-price 0.79` | inna cena GPU, jeśli test idzie na innej karcie |
| `--dry-run` | test bez GPU: sprawdza tylko zapis wyników |

Wyniki: `out/results.csv` (tabela), `out/results.json` (wszystkie czasy), `out/report.html` (tabela i obrazy).
