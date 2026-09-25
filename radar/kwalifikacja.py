"""Kwalifikacja kandydatów: strony -> fakty -> ocena -> wynik.csv.

    python -m radar.kwalifikacja zlecenia/<nazwa>

Fakty trafiają do fakty.jsonl i są używane ponownie w kolejnych przebiegach: po zmianie
reguł w profil.yaml przeliczenie nie kosztuje wywołań modelu. Fakty od nowa: usuń fakty.jsonl
(albo wiersze wybranych firm).
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

from radar.llm import LimitModelu
from radar.narzedzia.ekstrakcja import wyciagnij_fakty
from radar.narzedzia.ocena import ocen
from radar.narzedzia.pobieranie import pobierz_strony
from radar.profil import wczytaj_profil
from radar.typy import Fakty, Firma, Ocena, Profil


def _wiersz(firma: Firma, fakty: Fakty, ocena: Ocena, profil: Profil, uwagi: str) -> dict:
    def tekst(w):
        return "; ".join(map(str, w)) if isinstance(w, list) else ("" if w is None else w)

    return {
        "nazwa": firma.nazwa, "suma": ocena.suma, "www": firma.www, "telefon": firma.telefon,
        "adres": firma.adres,
        "trafienia": "; ".join(f"{t.regula} {t.punkty:+g}" for t in ocena.trafienia),
        "dowody": " | ".join(f"{t.regula}: „{t.dowod.cytat}” ({t.dowod.url})"
                             for t in ocena.trafienia if t.dowod),
        **{f"fakt_{n}": tekst(f.wartosc) if (f := fakty.pola.get(n)) else "" for n in profil.schemat},
        "zaczepka": "", "uwagi": uwagi, "zrodlo": firma.zrodlo, "zrodlo_url": firma.zrodlo_url,
    }


def kwalifikuj(katalog: Path) -> list[dict]:
    profil = wczytaj_profil(katalog)
    with open(katalog / "kandydaci.csv", encoding="utf-8-sig") as f:
        firmy = [Firma(**{k: v or None for k, v in w.items()}) for w in csv.DictReader(f)]
    plik_faktow = katalog / "fakty.jsonl"
    znane = {}
    if plik_faktow.exists():
        for linia in plik_faktow.read_text(encoding="utf-8").splitlines():
            fakty = Fakty.model_validate_json(linia)
            znane[fakty.firma] = fakty

    wiersze, przerwano = [], None
    for i, firma in enumerate(firmy, 1):
        uwagi, fakty = "", znane.get(firma.nazwa)
        if fakty is None:
            print(f"[{i}/{len(firmy)}] {firma.nazwa}: strony i fakty...", flush=True)
            try:
                strony = pobierz_strony(firma, profil.podstrony)
                if strony:
                    fakty = wyciagnij_fakty(strony, profil.schemat, profil.modele["ekstrakcja"])
                    fakty.firma = firma.nazwa
                    with open(plik_faktow, "a", encoding="utf-8") as f:
                        f.write(fakty.model_dump_json() + "\n")
                else:  # nie zapisujemy — przy następnym przebiegu spróbujemy znowu
                    uwagi = "brak www" if not firma.www else "strona niedostępna"
            except LimitModelu as e:  # następne firmy też by nie przeszły
                przerwano = str(e)
                break
            except Exception as e:  # jedna firma nie zatrzymuje całej listy
                uwagi = f"błąd: {type(e).__name__}: {e}"[:300]
        fakty = fakty or Fakty(firma=firma.nazwa)
        ocena = ocen(fakty, profil.reguly)
        print(f"[{i}/{len(firmy)}] {ocena.suma:+6.0f}  {firma.nazwa}  {uwagi}")
        wiersze.append(_wiersz(firma, fakty, ocena, profil, uwagi))

    if przerwano:
        print(f"PRZERWANO na {i}/{len(firmy)}: {przerwano}")
        print("Gotowe fakty są w fakty.jsonl — uruchom ponownie później, gotowe firmy pominie.")
    wiersze.sort(key=lambda w: -w["suma"])
    with open(katalog / "wynik.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(wiersze[0]) if wiersze else ["nazwa"])
        w.writeheader()
        w.writerows(wiersze)
    return wiersze


def main(argv: list[str]) -> None:
    if not argv:
        sys.exit("Użycie: python -m radar.kwalifikacja zlecenia/<nazwa>")
    katalog = Path(argv[0])
    wiersze = kwalifikuj(katalog)
    print(f"{len(wiersze)} firm -> {katalog / 'wynik.csv'}, fakty: {katalog / 'fakty.jsonl'}")


if __name__ == "__main__":
    main(sys.argv[1:])
