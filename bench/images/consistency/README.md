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

**7. Hugging Face** (na laptopie, raz). Na stronie [FLUX 3 Image Klein](https://huggingface.co/black-forest-labs/flux-3-image-klein)
zaakceptuj licencję. Potem w ustawieniach konta, „Access Tokens”, utwórz token „Fine-grained” tylko z prawem
odczytu publicznych repozytoriów z ograniczonym dostępem (public gated repos). Nie twórz tokenu „Write”.
Nie używaj `hf auth login`: zapisuje token jawnym tekstem na wspólnym serwerze. Token podajesz tylko na czas
sesji (krok 8) i unieważniasz po sesji (krok 10).

**8. Krótka gra na każdym modelu** (ta sesja). `testset_short.yaml`: 6 scen, runda 6 wraca do rundy 1,
1 seed, 4 warianty. Na model 33 obrazy i 6 scen złożonych z warstw. Każdy model osobno, żeby błąd jednego
nie zatrzymał reszty. W `tmux`, żeby zerwanie VPN nie przerwało pomiaru (powrót: `tmux attach -t dvn`):
```bash
tmux new -s dvn
eval "$(conda shell.bash hook)" && conda activate ~/data/conda/dvn-images
read -s HF_TOKEN && export HF_TOKEN    # wklej token, nic się nie wyświetli; nie trafia na dysk ani do historii
cd ~/data/dvn && git pull && cd bench/images/consistency
nvidia-smi
OUT=~/data/dvn-results/short
python run.py --testset testset_short.yaml --seeds 1 --models flux2-klein-4b --out $OUT
python run.py --testset testset_short.yaml --seeds 1 --models sdxl-ip --out $OUT
python run.py --testset testset_short.yaml --seeds 1 --models flux3-klein --out $OUT
```
Szacunek: kilka minut na model po pobraniu, najdłużej FLUX 3. Pierwsze pobranie wszystkich modeli
to ok. 50 GB, więc 15 do 40 minut zależnie od łącza serwera. Jeśli któryś model zgłosi błąd (nazwa parametru,
repozytorium, brak pamięci), zapisz ostatnie ok. 30 linii dla agenta i uruchom kolejny model.

**9. Oceny i raport** (ok. 5 minut, pobiera jeszcze detektor osób i modele ocen, ok. 3 GB):
```bash
python score.py --out $OUT
python report.py --out $OUT
pip freeze > $OUT/pip-freeze.txt
```
Pełny pomiar (`testset.yaml`, 22 sceny, kilka seedów, 2 do 3 h) zostaje na następny sprint:
ta sama komenda bez `--testset`, z `--seeds 2` i innym `--out`.

**10. Po każdej sesji: sprzątanie** (obowiązkowe):
```bash
nvidia-smi                                   # na liście nie może być naszego python
ps -u antpie -o pid,etime,cmd | grep python  # nic naszego nie zostało?
unset HF_TOKEN
tmux kill-session -t dvn
exit
```
Potem na Hugging Face unieważnij token („Access Tokens”, „Invalidate”). Modele zostają pobrane w `~/data/cache`,
więc kolejna sesja z tymi samymi modelami nie potrzebuje tokenu.
Konto jest wspólne z Krzyśkiem: zatrzymuj tylko swój proces przez `kill <PID>`, bez `pkill` i `killall`.

**11. Wyniki na laptop** (z laptopa). Konto i dane są usuwane na końcu semestru:
```bash
rsync -av -e "ssh -i ~/.ssh/id_ed25519" antpie@<adres serwera>:~/data/dvn-results/ data/dvn-results/
open data/dvn-results/short/report.html
```

**Koniec projektu:** usuń `~/data/dvn`, `~/data/dvn-results`, `~/data/cache` i `~/data/conda/dvn-images`.
