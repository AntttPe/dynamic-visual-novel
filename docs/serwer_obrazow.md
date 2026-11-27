# Serwer obrazów: uruchomienie od zera

Gra (na laptopie) wysyła opis sceny do serwera obrazów na maszynie z GPU, a ten rysuje obraz modelem FLUX.2 klein.
Połączenie idzie przez tunel SSH, więc serwer nie jest widoczny z zewnątrz.

```
laptop: gra (Docker, localhost:8000)  ──tunel SSH, port 8420──>  serwer GPU: python serve.py
```

Ten poradnik jest dla nowego konta na serwerze, na którym jeszcze nic nie ma.
`<login>` i `<adres serwera>` dostajesz od zespołu. `<adres repo>` to link z GitLaba uczelni: w repo kursu kliknij
**Code**, potem skopiuj **Clone with HTTPS**. Nasz kod jest tam na gałęzi `zolc/dynamic-visual-novel`.
Wszystko robisz przy włączonym VPN uczelni.

## Część 1. Instalacja (tylko raz, ok. 30 minut)

**1. Zaloguj się i sprawdź, czy GPU jest wolne.** Jeśli działa na nim proces kogoś innego, poczekaj.
```bash
ssh <login>@<adres serwera>
nvidia-smi        # zapamiętaj "CUDA Version" w prawym górnym rogu
df -h ~/data      # potrzeba ok. 30 GB wolnego miejsca
```

**2. Duże pliki do `~/data`.** Katalog domowy jest mały, a modele mają kilkanaście GB.
```bash
cat >> ~/.bashrc <<'EOF'
export HF_HOME=~/data/cache/huggingface
export PIP_CACHE_DIR=~/data/cache/pip
export CONDA_PKGS_DIRS=~/data/cache/conda-pkgs
export U2NET_HOME=~/data/cache/u2net
EOF
source ~/.bashrc
```

**3. Środowisko Conda** (bez `sudo`; `git` i `tmux` też instalujemy w środowisku, bo na serwerze ich nie ma).
```bash
eval "$(conda shell.bash hook)"
conda create -p ~/data/conda/dvn-images --override-channels -c conda-forge python=3.12 pip git tmux -y
conda activate ~/data/conda/dvn-images
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```
`cu128` pasuje do CUDA 12.8 i nowszej. Przy CUDA 12.6 wpisz `cu126`, przy 12.4 `cu124`.

**4. Kod i biblioteki.**
```bash
cd ~/data && git clone -b zolc/dynamic-visual-novel <adres repo> dvn
cd ~/data/dvn/bench/images/consistency
pip install -r requirements.txt
python -c "import torch; print(torch.cuda.is_available())"     # ma wypisać True
```
Jeśli GitLab pyta o hasło, użyj tokenu dostępu z GitLaba (prawo `read_repository`), nie hasła do konta.

Gotowe. Model pobierze się sam przy pierwszym uruchomieniu (krok 5).

## Część 2. Każda sesja gry

**5. Okno 1, serwer GPU: uruchom serwer obrazów.**
```bash
ssh <login>@<adres serwera>
nvidia-smi                                   # czy GPU jest wolne
eval "$(conda shell.bash hook)" && conda activate ~/data/conda/dvn-images
tmux ls                                      # czy nie działa już stara sesja z serve.py
tmux new -s dvn
```
Już w tmux (nowa sesja nie ma aktywnego środowiska, więc aktywujesz je jeszcze raz):
```bash
eval "$(conda shell.bash hook)" && conda activate ~/data/conda/dvn-images
cd ~/data/dvn && git pull && cd bench/images/consistency
python serve.py
```
Czekaj na napis `Gotowe: 127.0.0.1:8420`. Za pierwszym razem trwa to kilka do kilkunastu minut (pobieranie modelu),
potem ok. minuty. Jeśli `tmux ls` pokazał sesję `dvn`, zamiast `tmux new` wpisz `tmux attach -t dvn`: serwer może już działać.

**6. Okno 2, laptop: tunel.** Komenda nic nie wypisuje i tak ma być. Zostaw okno otwarte.
```bash
ssh -N -L 8420:127.0.0.1:8420 <login>@<adres serwera>
```

**7. Laptop: połącz grę z serwerem** (tylko raz). W pliku `.env` gry usuń `#` przed linią:
```
IMAGE_SERVER_URL=http://host.docker.internal:8420
```
i uruchom grę ponownie: `docker compose up -d --force-recreate app`.

**8. Graj** na http://localhost:8000. Obraz sceny pojawia się kilka sekund po tekście.

**9. Po graniu wyłącz wszystko.** W oknie 1: `Ctrl+C`, `exit`, `exit`. W oknie 2: `Ctrl+C`.

## Zasady serwera

* Serwer obrazów nie może działać na stałe. Wyłączaj go po graniu (sam wyłączy się po 30 minutach bez pracy).
* Uruchamiaj tylko przy wolnym GPU. Instaluj wyłącznie w środowisku Conda, wszystko duże trzymaj w `~/data`.
* Adresu serwera, loginów i tokenów nie wpisuj do repo.

## Gdy nie ma obrazów

| Objaw | Co sprawdzić |
|---|---|
| W oknie 1 nie ma `Gotowe` | Czytaj błąd. `CUDA out of memory`: GPU zajęte, poczekaj. Brak `torch`: nie aktywowałeś środowiska Conda |
| `serve.py` działa, gra nie rysuje | Czy tunel w oknie 2 działa? Na laptopie: `curl http://localhost:8420/health` |
| Tunel działa, gra nie rysuje | Czy w `.env` linia `IMAGE_SERVER_URL` jest bez `#` i czy był `docker compose up -d --force-recreate app`? |
| Gracz z konta nie ma obrazów | W panelu administratora ustaw graczowi grafikę „Serwer obrazów z .env” |
| Serwer sam się wyłączył | Minęło 30 minut bez obrazów. Uruchom `python serve.py` jeszcze raz |
