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
