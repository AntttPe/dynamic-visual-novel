# Pomiar spójności postaci i lokacji (zadanie Z1)

Sprawdza, która architektura generowania obrazów utrzymuje wygląd postaci i miejsc w długiej grze:
czy bohater w rundzie 20 wygląda tak samo jak w rundzie 1, gdy wraca w to samo miejsce.

Każdy model najpierw rysuje obrazy wzorcowe (3 postacie i 4 lokacje z `testset.yaml`), potem 22 sceny
z zaplanowanymi powrotami (scena 20 powtarza scenę 1, 19 powtarza 3, 17 powtarza 5, 15 powtarza 2, 14 powtarza 4)
w czterech wariantach:

| Wariant | Co model dostaje | Po co |
|---|---|---|
| `text` | sam opis postaci i miejsca (karta postaci tylko tekstem) | punkt odniesienia: czy bez obrazu postać się rozjeżdża |
| `anchor` | opis i obrazy wzorcowe postaci i lokacji ze sceny | stały wzorzec jako obraz wejściowy |
| `chain` | opis i ostatni obraz z daną postacią lub lokacją | czy błędy się kumulują |
| `layers` | jak w visual novel: tło = wzorzec lokacji (rysowany raz), postać rysowana osobno ze swojego wzorca, wycięta i nałożona | architektura warstwowa |

Każda scena ma własny seed (seed + numer sceny), taki sam we wszystkich wariantach.

| Model (`--models`) | Co to jest |
|---|---|
| `sdxl-ip` | SDXL z IP-Adapterem, punkt odniesienia |
| `flux2-klein-4b` | FLUX.2 [klein] 4B, 4 kroki, Apache 2.0 |
| `flux3-klein` | FLUX 3 Image Klein, do 10 obrazów wejściowych, wymaga akceptacji licencji na Hugging Face |

Pliki: `run.py` (generowanie, wznawianie), `compose.py` (składanie warstw, wycinanie tła),
`score.py` (wycinki postaci i oceny), `report.py` (raport HTML), `models.py` (adaptery modeli),
`testset.yaml` (postacie, lokacje, sceny). Testy logiki bez GPU: `pytest tests/test_image_bench.py` w kontenerze gry.

## Co mierzymy

- **Postać w kolejnych rundach:** detektor osób (OWLv2) wycina postacie, wycinek porównujemy z wycinkiem
  z pierwszego pojawienia się tej postaci (k = 1) i z wzorcem. Podobieństwo = cosinus embeddingów DINOv2
  (wygląd) i CLIP (treść), wyżej = bardziej podobne. Raport pokazuje je dla k od 2 do 22.
- **Powroty:** scena z powrotem kontra pierwsza wizyta: postacie (wycinki) i cała scena. Główna tabela raportu.
- **Znalezienie postaci:** czy detektor znalazł wszystkie postacie ze sceny (zniknięcie postaci to też błąd).
- **Lokacja:** cała scena kontra wzorzec lokacji. **clipscore:** zgodność obrazu z opisem sceny.
- **Czas i VRAM** każdego obrazu. W `layers` czas sceny = obrazy postaci + składanie (tło z cache).

Wycinki są zapisywane w `crops/`, gotowe dla sędziego obrazów (zadanie Z5).
Ograniczenie: przy kilku postaciach wycinki przypisujemy do postaci po podobieństwie do ich wzorców.

## Uruchomienie na serwerze GPU instytutu

Komendy wpisujesz sam na serwerze. Ta sama lista z przyciskami „Kopiuj” jest na stronie z komendami (link u Antka).
Zasady serwera są w `PROGRESS.md` (sekcja „Zasady serwera GPU instytutu”). Adresu serwera nie wpisujemy do repo.

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
df -h ~ ~/data      # na ~/data potrzeba ok. 80 GB
which conda git tmux
```
Jeśli brakuje `conda`, nie instaluj niczego na własną rękę, tylko zapytaj prowadzącego (regulamin:
niestandardowe wymagania konsultujemy). Bez `tmux` użyj `screen -S dvn`.

**4. Wszystko duże w `~/data`** (raz). Dysk domowy jest mały, a Conda, pip, Hugging Face i rembg
domyślnie zapisują w katalogu domowym:
```bash
cat >> ~/.bashrc <<'EOF'
export HF_HOME=~/data/cache/huggingface
export PIP_CACHE_DIR=~/data/cache/pip
export CONDA_PKGS_DIRS=~/data/cache/conda-pkgs
export U2NET_HOME=~/data/cache/u2net
EOF
source ~/.bashrc
```

**5. Środowisko Conda** (raz). Bez `sudo`, pakiety tylko wewnątrz środowiska:
```bash
eval "$(conda shell.bash hook)"
conda create -p ~/data/conda/dvn-images python=3.12 -y
conda activate ~/data/conda/dvn-images
conda install pip -y
# torch pod wersję CUDA z nvidia-smi: CUDA 12.8 lub nowsza -> cu128, 12.6 -> cu126, 12.4 -> cu124
pip install torch --index-url https://download.pytorch.org/whl/cu128
```

**6. Kod** (raz, potem tylko `cd ~/data/dvn && git pull`):
```bash
cd ~/data && git clone https://github.com/AntttPe/dynamic-visual-novel.git dvn
cd ~/data/dvn/bench/images/consistency
pip install -r requirements.txt
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

**7. Hugging Face** (raz). Na stronie [FLUX 3 Image Klein](https://huggingface.co/black-forest-labs/flux-3-image-klein)
zaakceptuj licencję, potem utwórz token „Read” w ustawieniach konta. Token wklejasz tylko na serwerze, nie do repo:
```bash
hf auth login            # starsza wersja: huggingface-cli login
```

**8. Krótki test** (3 sceny, 1 seed: ok. 15 do 40 minut razem z pobieraniem modeli). W `tmux`,
żeby zerwanie VPN nie przerwało pomiaru (powrót: `tmux attach -t dvn`):
```bash
tmux new -s dvn
eval "$(conda shell.bash hook)" && conda activate ~/data/conda/dvn-images
cd ~/data/dvn/bench/images/consistency
nvidia-smi
python run.py --models flux2-klein-4b --seeds 1 --scenes 3 --out ~/data/dvn-results/consistency-test
python run.py --models sdxl-ip --seeds 1 --scenes 3 --out ~/data/dvn-results/consistency-test
python run.py --models flux3-klein --seeds 1 --scenes 3 --out ~/data/dvn-results/consistency-test
python score.py --out ~/data/dvn-results/consistency-test
python report.py --out ~/data/dvn-results/consistency-test
```
Jeśli któryś krok zgłosi błąd (nazwa parametru, repozytorium, brak pamięci), skopiuj ostatnie ok. 30 linii
do agenta. Adaptery FLUX nie były jeszcze uruchamiane na GPU.

**9. Pełny pomiar.** Ok. 980 obrazów na 3 seedach (109 na model i seed). Szacunek: 2 do 3 godzin, z czego najwięcej
FLUX 3 (odciążanie do RAM). Na start można `--seeds 2` (ok. 1,5 do 2 godzin). Ta sama komenda po przerwaniu
wznawia od miejsca, gdzie stanęła:
```bash
python run.py --models flux2-klein-4b sdxl-ip flux3-klein --seeds 2 --out ~/data/dvn-results/consistency
python score.py --out ~/data/dvn-results/consistency
python report.py --out ~/data/dvn-results/consistency
pip freeze > ~/data/dvn-results/consistency/pip-freeze.txt
```

**10. Po każdej sesji: sprzątanie** (obowiązkowe):
```bash
nvidia-smi                                   # na liście nie może być naszego python
ps -u antpie -o pid,etime,cmd | grep python  # nic naszego nie zostało?
tmux kill-session -t dvn
exit
```
Konto jest wspólne z Krzyśkiem: zatrzymuj tylko swój proces przez `kill <PID>`, bez `pkill` i `killall`.

**11. Wyniki na laptop** (z laptopa). Konto i dane są usuwane na końcu semestru:
```bash
rsync -av -e "ssh -i ~/.ssh/id_ed25519" antpie@<adres serwera>:~/data/dvn-results/ data/dvn-results/
open data/dvn-results/consistency/report.html
```

**Koniec projektu:** usuń `~/data/dvn`, `~/data/dvn-results`, `~/data/cache` i `~/data/conda/dvn-images`.
