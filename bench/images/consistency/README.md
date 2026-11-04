# Pomiar spójności postaci i lokacji (zadanie Z1)

Sprawdza, czy model obrazów rysuje tę samą postać i to samo miejsce tak samo w kolejnych scenach.
Każdy model najpierw rysuje obrazy wzorcowe (postacie i lokacje z `testset.yaml`), potem każdą
z 10 scen w trzech wariantach:

| Wariant | Co model dostaje | Po co |
|---|---|---|
| `text` | sam opis | punkt odniesienia: czy bez obrazu postać się rozjeżdża |
| `anchor` | opis i obrazy wzorcowe postaci i lokacji ze sceny | główny kandydat do gry |
| `chain` | opis i ostatni obraz z daną postacią lub lokacją | czy błędy się kumulują |

| Model (`--models`) | Co to jest |
|---|---|
| `sdxl-ip` | SDXL z IP-Adapterem, punkt odniesienia |
| `flux2-klein-4b` | FLUX.2 [klein] 4B, 4 kroki, Apache 2.0 |
| `flux3-klein` | FLUX 3 Image Klein, do 10 obrazów wejściowych, wymaga akceptacji licencji na Hugging Face |

Pliki: `run.py` (generowanie, wznawianie), `score.py` (oceny DINOv2 i CLIP), `report.py` (raport HTML),
`models.py` (adaptery modeli), `testset.yaml` (postacie, lokacje, sceny).
Testy logiki bez GPU: `pytest tests/test_image_bench.py` w kontenerze gry.

## Uruchomienie na serwerze GPU instytutu

Komendy wpisujesz sam na serwerze. Zasady serwera są w `PROGRESS.md` (sekcja „Zasady serwera GPU instytutu”),
adres serwera jest w nocie od prowadzącego (nie wpisujemy go do repo).

**1. Logowanie** (VPN instytutu musi być włączony):
```bash
ssh -i ~/.ssh/id_ed25519 antpie@<adres serwera>
```

**2. Na samym początku: `PROJECT.md`** w katalogu głównym serwera. Najpierw zobacz format pliku,
potem dopisz swoje dane tak jak inni (imię i nazwisko, projekt, kontakt):
```bash
cat /PROJECT.md
nano /PROJECT.md
```

**3. Czy można zaczynać.** Jeśli GPU jest zajęte przez kogoś innego, poczekaj:
```bash
nvidia-smi          # zajętość GPU i wersja CUDA (prawy górny róg)
top                 # CPU i RAM (wyjście: q)
df -h ~ ~/data      # miejsce na dysku domowym i na ~/data
```

**4. Wszystko duże w `~/data`.** Dysk domowy jest mały, więc środowisko Conda, cache pip
i modele z Hugging Face (kilkadziesiąt GB) też idą do `~/data`. Te 3 linie wpisz przy każdym logowaniu
(albo dopisz na koniec `~/.bashrc`):
```bash
export HF_HOME=~/data/cache/huggingface
export PIP_CACHE_DIR=~/data/cache/pip
export CONDA_PKGS_DIRS=~/data/cache/conda-pkgs
```

**5. Środowisko Conda** (raz). Bez `sudo`, pakiety tylko wewnątrz środowiska:
```bash
conda create -p ~/data/conda/dvn-images python=3.12 -y
conda activate ~/data/conda/dvn-images
conda install pip -y
# torch pod wersję CUDA z nvidia-smi: CUDA 12.8 lub nowsza -> cu128, 12.6 -> cu126, 12.4 -> cu124
pip install torch --index-url https://download.pytorch.org/whl/cu128
```

**6. Kod** (raz, potem tylko `git pull`):
```bash
cd ~/data && git clone https://github.com/AntttPe/dynamic-visual-novel.git dvn
cd ~/data/dvn/bench/images/consistency
pip install -r requirements.txt
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

**7. Hugging Face** (raz). Na stronie [FLUX 3 Image Klein](https://huggingface.co/black-forest-labs/flux-3-image-klein-base)
zaakceptuj licencję, potem utwórz token „Read” w ustawieniach konta. Token wklejasz tylko na serwerze, nie do repo:
```bash
hf auth login
```

**8. Krótki test** (ok. 10 do 15 minut, z pobieraniem modeli dłużej). Uruchamiaj w `tmux`, żeby zerwanie VPN
nie przerwało pomiaru:
```bash
tmux new -s dvn                 # powrót po zerwaniu: tmux attach -t dvn
conda activate ~/data/conda/dvn-images
cd ~/data/dvn/bench/images/consistency
python run.py --models flux2-klein-4b --seeds 1 --scenes 3 --out ~/data/dvn-results/consistency-test
python run.py --models sdxl-ip --seeds 1 --scenes 3 --out ~/data/dvn-results/consistency-test
python run.py --models flux3-klein --seeds 1 --scenes 3 --out ~/data/dvn-results/consistency-test
python report.py --out ~/data/dvn-results/consistency-test
```
Jeśli któryś model zgłosi błąd (nazwa parametru, repozytorium, brak pamięci), skopiuj komunikat do agenta.
FLUX.2 klein i FLUX 3 Image Klein są nowe, więc adaptery w `models.py` mogą wymagać poprawki.

**9. Pełny pomiar** (ok. 30 do 60 minut). Ta sama komenda po przerwaniu wznawia od miejsca, gdzie stanęła:
```bash
python run.py --models sdxl-ip flux2-klein-4b flux3-klein --out ~/data/dvn-results/consistency
python score.py --out ~/data/dvn-results/consistency
python report.py --out ~/data/dvn-results/consistency
pip freeze > ~/data/dvn-results/consistency/pip-freeze.txt   # wersje bibliotek do raportu
```

**10. Po pomiarze: sprzątanie** (obowiązkowe):
```bash
nvidia-smi          # na liście nie może być naszych procesów python
exit                # zamyka tmux; sesje sprawdzisz: tmux ls
```

**11. Wyniki na laptop** (z laptopa, nie z serwera). Konto i dane są usuwane na końcu semestru:
```bash
rsync -av -e "ssh -i ~/.ssh/id_ed25519" antpie@<adres serwera>:~/data/dvn-results/consistency/ data/consistency/
open data/consistency/report.html
```

**Koniec projektu:** usuń `~/data/dvn`, `~/data/dvn-results`, `~/data/cache` i `~/data/conda/dvn-images`.

## Co mierzymy

- **Czas i VRAM** każdego obrazu (`results.jsonl`).
- **dino, clip:** podobieństwo sceny do obrazu wzorcowego postaci lub lokacji (cosinus embeddingów, wyżej = bardziej podobne).
  Raport pokazuje je w zależności od k (k-te pojawienie się postaci), czyli jak szybko postać się rozjeżdża.
- **clipscore:** zgodność obrazu z opisem sceny.

Ograniczenie: porównujemy cały obraz, więc podobieństwo postaci miesza się z tłem. Dokładniej oceni to
sędzia obrazów (zadanie Z5).
