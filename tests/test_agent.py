"""python tests/test_agent.py — pętla odkrywania bez sieci i bez modelu."""
import csv
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import radar.agent as agent
from radar.llm import Wywolanie
from radar.typy import Kontekst, Miejsce, Profil, Strona

MIEJSCA = [Miejsce(place_id="p1", nazwa="Alfa Sp. z o.o.", www="https://www.alfa.pl/"),
           Miejsce(place_id="p2", nazwa="Beta", www="https://alfa.pl/kontakt")]  # ta sama domena co p1
HTML = "<html><body><h1>Członkowie</h1><p>Gamma Trans S.A.</p><a href='/delta'>Delta</a></body></html>"

agent.szukaj_miejsca = lambda fraza, obszar: MIEJSCA
agent.pobierz = lambda url: Strona(url=url, status=200, typ="text/html", tresc=HTML, pobrano=datetime.now())

SCENARIUSZ = [
    ("", [Wywolanie("1", "szukaj_miejsca", {"fraza": "x", "obszar": "Gdynia"})]),
    ("", [Wywolanie("2", "zapisz_kandydatow", {"firmy": [{"place_id": "p1"}, {"place_id": "p2"},
                                                          {"place_id": "zmyslone"}]})]),
    ("", [Wywolanie("3", "pobierz", {"url": "https://izba.pl/lista"})]),
    ("", [Wywolanie("4", "zapisz_kandydatow", {"firmy": [
        {"nazwa": "Gamma Trans", "zrodlo_url": "https://izba.pl/lista"},
        {"nazwa": "Omega Log", "zrodlo_url": "https://izba.pl/lista"}]}),
          Wywolanie("5", "nie_ma_takiego", {}), Wywolanie("6", "pobierz", None)]),
    ("Koniec.", []),
    ("Nic więcej.", []),  # odpowiedź na ponaglenie (cel 3, mamy 2)
]
wyniki_narzedzi = []


class FalszywaRozmowa:
    def __init__(self, *a):
        self.kroki = iter(SCENARIUSZ)

    def krok(self, tekst=None, wyniki=None):
        wyniki_narzedzi.extend(wyniki or [])
        return next(self.kroki)


agent.Rozmowa = FalszywaRozmowa

with tempfile.TemporaryDirectory() as d:
    k = Kontekst(kogo_szukamy="x", produkt={"nazwa": "p", "opis": "o", "problem": "q"}, obszar="o",
                 pracownicy_min=1, pracownicy_max=9, ile_kandydatow=3)
    p = Profil(lokalizacje=["Gdynia"], frazy_miejsca=["x"], frazy_web=[], pkd=[], schemat={}, reguly={},
               modele={"odkrywanie": "hermes:x"})
    kandydaci = agent.Odkrywanie(Path(d), k, p).uruchom()

    assert [f.nazwa for f in kandydaci] == ["Alfa Sp. z o.o.", "Gamma Trans"], kandydaci
    assert kandydaci[0].zrodlo == "szukaj_miejsca:x|Gdynia"
    assert kandydaci[1].zrodlo_url == "https://izba.pl/lista"
    wynik_zapisu = dict((i, w) for i, w, _ in wyniki_narzedzi)
    assert "nieznane place_id" in wynik_zapisu["2"] and "duplikatów 1" in wynik_zapisu["2"]
    assert "nie występuje na stronie" in wynik_zapisu["4"]
    assert "Delta -> https://izba.pl/delta" in wynik_zapisu["3"]
    assert [b for _, _, b in wyniki_narzedzi] == [False, False, False, False, True, True]
    wiersze = list(csv.DictReader(open(Path(d) / "kandydaci.csv", encoding="utf-8-sig")))
    assert len(wiersze) == 2 and all(w["zrodlo"] for w in wiersze)
    log = [json.loads(l) for l in open(Path(d) / "log.jsonl", encoding="utf-8")]
    assert [l["typ"] for l in log if l["typ"] in ("start", "koniec")] == ["start", "koniec"]
    assert sum(l["typ"] == "narzedzie" for l in log) == 2 and sum(l["typ"] == "kandydat" for l in log) == 2

print("ok")
