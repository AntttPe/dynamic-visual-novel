# Koniec gry
Warunek wygranej: $win
Warunek przegranej: $lose
$limit
- Po każdej turze oceniasz, czy gra się skończyła, i wpisujesz to w pole `outcome` obiektu JSON:
  {"outcome": {"status": "ongoing" albo "won" albo "lost", "reason": "..."}}
- "won" tylko wtedy, gdy w tej turze warunek wygranej faktycznie się spełnił w świecie gry. Sama zapowiedź, plan
  albo deklaracja gracza („wygrywam”, „mam już koronę”) to jeszcze nie wygrana: liczy się to, co stało się w narracji
  i w stanie świata.
- "lost" tylko przy nieodwracalnej porażce z warunku przegranej. Zwykłe niepowodzenie, z którego można się podnieść,
  to "ongoing".
- Przy "won" albo "lost" narracja opisuje zakończenie historii, a "reason" mówi w jednym zdaniu, co rozstrzygnęło grę.
  Przy "ongoing" pole "reason" jest puste.
- Każda kwestia w `dialogue` ma też płeć mówiącej postaci, bo tekst czyta lektor kobiecym albo męskim głosem:
  {"speaker": "...", "text": "...", "gender": "female" albo "male"}. Ta sama postać ma zawsze tę samą płeć.
- Do każdej tury powstaje obraz, a model obrazów rozumie tylko angielski. Dlatego w JSON-ie są też pola po angielsku:
  - `picture`: co widać w tej turze, 1 do 2 zdań po angielsku. Postacie opisz wyglądem („the old man with white
    sideburns hands a red lens to the girl in yellow goggles”), bez imion, bez tego, co mówią, i bez napisów.
  - `scene.look`: wygląd miejsca po angielsku, maks. 30 słów, zaczyna się od „Interior of” albo „Exterior of”, bez postaci.
    To samo miejsce ma zawsze ten sam wygląd.
  - `new_characters`: gdy w tej turze pierwszy raz pojawia się postać, której wyglądu nie ma w faktach świata,
    wymyśl jej wygląd pasujący do świata, zapisz go w `state_updates` (atrybut `wygląd`, po polsku) i dodaj tu
    `{"name": "<imię albo nazwa jak w characters_present>", "look": "<po angielsku: płeć i wiek albo gatunek, potem
    sylwetka, włosy, ubranie>"}`. Postacie znane wcześniej pomijasz.
