"""python tests/test_kwalifikacja.py — strony -> fakty -> ocena -> wynik.csv, bez sieci i modelu."""
import csv
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

KORZEN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KORZEN))

import radar.narzedzia.ekstrakcja as ekstrakcja
import radar.narzedzia.pobieranie as pobieranie
from radar.kwalifikacja import kwalifikuj
from radar.typy import Firma, Strona

STRONY = {
    "https://alfa.pl/": "<p>Alfa Spedycja</p><a href='/o-nas'>O nas</a><a href='/dla-przewoznikow'>Dla "
                        "przewoźników</a><a href='/blog/wpis'>Blog</a><a href='https://obca.pl/kariera'>X</a>",
    "https://alfa.pl/o-nas": "<p>Zatrudniamy 120 osób w trzech oddziałach.</p>",
    "https://alfa.pl/dla-przewoznikow": "<p>Fakturę wraz z oryginałem CMR prosimy przesłać na adres biura.</p>",
}
pobrane = []


def falszywe_pobierz(url):
    pobrane.append(url)
    if url not in STRONY:
        raise pobieranie.ZablokowanePrzezRobots(url)
    return Strona(url=url, status=200, typ="text/html", tresc=STRONY[url], pobrano=datetime.now())


pobieranie.pobierz = falszywe_pobierz

# pobierz_strony: główna + podstrony pasujące do słów, bez bloga i obcej domeny
strony = pobieranie.pobierz_strony(Firma(nazwa="Alfa", www="https://alfa.pl/?utm_source=x", zrodlo="t"),
                                   ["przewoźnik"])
assert {s.url for s in strony} == set(STRONY), [s.url for s in strony]
assert not any("blog" in u or "obca" in u for u in pobrane)

wywolan = []


def falszywy_model(model, prompt, schemat):
    wywolan.append(model)
    assert "Fakturę wraz z oryginałem CMR" in prompt
    return schemat.model_validate({n: None for n in schemat.model_fields} | {
        "liczba_pracownikow": {"wartosc": 120, "cytat": "Zatrudniamy 120 osób", "url": "https://alfa.pl/"},
        "instrukcja_dokumentow_dla_przewoznikow": {
            "wartosc": True, "cytat": "fakturę wraz z oryginałem CMR prosimy przesłać",
            "url": "https://alfa.pl/dla-przewoznikow"},
        "uslugi_celne": {"wartosc": True, "cytat": "świadczymy pełną obsługę celną", "url": "https://alfa.pl/"},
    })


ekstrakcja.json_wg_schematu = falszywy_model

with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    shutil.copy(KORZEN / "zlecenia/spedycja-trojmiasto/profil.yaml", d)
    with open(d / "kandydaci.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(Firma.model_fields))
        w.writeheader()
        w.writerow(Firma(nazwa="Bez WWW", zrodlo="t").model_dump())
        w.writerow(Firma(nazwa="Alfa", www="https://alfa.pl/?utm_source=x", zrodlo="t").model_dump())

    wiersze = kwalifikuj(d)
    alfa, bez = wiersze
    assert alfa["nazwa"] == "Alfa" and alfa["suma"] == 25, alfa  # instrukcja +25; celne zmyślone -> 0
    assert alfa["fakt_liczba_pracownikow"] == 120 and alfa["fakt_uslugi_celne"] == ""
    assert "https://alfa.pl/o-nas" in alfa["dowody"] or "instrukcja" in alfa["dowody"]
    assert bez["uwagi"] == "brak www" and bez["suma"] == 0
    assert len(wywolan) == 1

    kwalifikuj(d)  # drugi przebieg: fakty z fakty.jsonl, bez modelu
    assert len(wywolan) == 1
    assert list(csv.DictReader(open(d / "wynik.csv", encoding="utf-8-sig")))[0]["nazwa"] == "Alfa"

print("ok")
