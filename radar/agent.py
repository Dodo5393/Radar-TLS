"""Pętla odkrywania kandydatów.

    python -m radar.agent zlecenia/<nazwa>

Czyta kontekst.yaml i profil.yaml, zapisuje kandydaci.csv, dopisuje do log.jsonl.
Źródło firmy ustala kod, nie model: z Places bierzemy tylko place_id widziane w tym przebiegu,
ze stron — tylko firmy, których nazwa występuje na stronie pobranej w tym przebiegu.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from radar.llm import Narzedzie, Rozmowa, Wywolanie
from radar.narzedzia.pobieranie import pobierz
from radar.narzedzia.places import szukaj_miejsca
from radar.profil import wczytaj_kontekst, wczytaj_profil
from radar.typy import Firma, Kontekst, Miejsce, Profil

MAX_KROKOW = 60
LIMIT_TEKSTU = 12_000
LIMIT_LINKOW = 150

NARZEDZIA = [
    Narzedzie("szukaj_miejsca", "Szuka firm w Mapach Google. Zwraca do 60 wyników: place_id, nazwa, adres, www.",
              {"type": "object", "properties": {
                  "fraza": {"type": "string", "description": "czego szukać, bez miejscowości"},
                  "obszar": {"type": "string", "description": "jedna miejscowość"}},
               "required": ["fraza", "obszar"]}),
    Narzedzie("pobierz", "Pobiera stronę WWW. Zwraca tekst (obcięty) i listę linków. "
                         "Tylko adresy widziane w wynikach lub na pobranych stronach.",
              {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}),
    Narzedzie("zapisz_kandydatow",
              "Zapisuje kandydatów. Każdy element: {place_id} dla wyniku z szukaj_miejsca ALBO "
              "{nazwa, www?, zrodlo_url} dla firmy znalezionej na stronie pobranej narzędziem pobierz.",
              {"type": "object", "properties": {"firmy": {"type": "array", "items": {
                  "type": "object", "properties": {
                      "place_id": {"type": "string"}, "nazwa": {"type": "string"},
                      "www": {"type": "string"}, "zrodlo_url": {"type": "string"}}}}},
               "required": ["firmy"]}),
]

SYSTEM = """\
Zbierasz kandydatów na klientów B2B. Cel: {ile} firm pasujących do opisu.

KOGO SZUKAMY: {kogo}
OBSZAR: {obszar}
CO SPRZEDAJEMY: {produkt} — {problem}

Profil wyszukiwania (przygotowany i sprawdzony wcześniej):
- lokalizacje: {lokalizacje}
- frazy do Map Google: {frazy}

Jak pracować:
1. Łącz frazy z lokalizacjami, zaczynając od największych miejscowości i najszerszych fraz.
2. Po każdym wyszukiwaniu oceń wyniki względem opisu KOGO SZUKAMY i zapisz trafne
   (zapisz_kandydatow). Wielkości firmy i jej problemów nie oceniasz — robi to późniejszy
   etap. Odrzucaj tylko firmy wyraźnie spoza opisu (inna działalność, instytucje, sklepy).
3. Dużo nietrafnych wyników → zmień frazę. Same duplikaty → zmień lokalizację lub frazę.
4. pobierz służy do sprawdzenia niejasnego wyniku albo do przejrzenia listy firm
   (katalog, izba, lista wystawców), której adres już widziałeś. Nie wymyślaj adresów.
5. Zapisuj po każdym wyszukiwaniu, nie na końcu.
Gdy zbierzesz {ile} firm albo skończą się sensowne pomysły, odpowiedz krótkim podsumowaniem
bez wywoływania narzędzi.
"""


def _slowa(tekst: str) -> str:
    return " ".join(re.findall(r"\w+", tekst.lower()))


def _domena(www: str | None) -> str | None:
    if not www:
        return None
    return urlsplit(www if "//" in www else f"//{www}").netloc.lower().removeprefix("www.") or None


def _tekst_strony(html: str, url: str) -> tuple[str, list[tuple[str, str]]]:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    linki = {}
    for a in soup.find_all("a", href=True):
        linki.setdefault(urljoin(url, a["href"]), a.get_text(" ", strip=True))
    return soup.get_text(" ", strip=True), [(u, t) for u, t in linki.items() if u.startswith("http")]


class Odkrywanie:
    def __init__(self, katalog: Path, kontekst: Kontekst, profil: Profil):
        self.katalog, self.kontekst, self.profil = katalog, kontekst, profil
        self.miejsca: dict[str, tuple[Miejsce, str]] = {}  # place_id -> (miejsce, zrodlo)
        self.strony: dict[str, str] = {}  # url -> tekst strony pobranej w tym przebiegu
        self.kandydaci: list[Firma] = []
        self._klucze: set[str] = set()  # place_id, domena, nazwa — do usuwania duplikatów

    def loguj(self, **wpis) -> None:
        with open(self.katalog / "log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"czas": datetime.now().isoformat(timespec="seconds"), **wpis},
                               ensure_ascii=False) + "\n")

    # --- narzędzia ---

    def t_szukaj_miejsca(self, fraza: str, obszar: str) -> str:
        wyniki = szukaj_miejsca(fraza, obszar)
        for m in wyniki:
            self.miejsca.setdefault(m.place_id, (m, f"szukaj_miejsca:{fraza}|{obszar}"))
        self.loguj(typ="narzedzie", narzedzie="szukaj_miejsca", fraza=fraza, obszar=obszar, wynikow=len(wyniki))
        return "\n".join(json.dumps({
            "place_id": m.place_id, "nazwa": m.nazwa, "adres": m.adres, "www": m.www,
            "kategorie": m.kategorie[:3], **({"juz_zapisana": True} if m.place_id in self._klucze else {}),
        }, ensure_ascii=False) for m in wyniki) or "brak wyników"

    def t_pobierz(self, url: str) -> str:
        s = pobierz(url)
        tekst, linki = _tekst_strony(s.tresc, s.url) if "html" in s.typ else (s.tresc, [])
        self.strony[url] = self.strony[s.url] = tekst
        self.loguj(typ="narzedzie", narzedzie="pobierz", url=url, status=s.status, z_cache=s.z_cache,
                   znakow=len(tekst))
        return (f"URL: {s.url}  status: {s.status}\n"
                f"TEKST ({min(len(tekst), LIMIT_TEKSTU)} z {len(tekst)} znaków):\n{tekst[:LIMIT_TEKSTU]}\n"
                f"LINKI ({min(len(linki), LIMIT_LINKOW)} z {len(linki)}):\n"
                + "\n".join(f"{t} -> {u}" for u, t in linki[:LIMIT_LINKOW]))

    def t_zapisz_kandydatow(self, firmy: list[dict]) -> str:
        gotowe, odrzucone = [], []
        for arg in firmy:
            wynik = self._firma(arg)
            (odrzucone.append(f"{arg}: {wynik}") if isinstance(wynik, str) else gotowe.append(wynik))
        dodane = self.zapisz_kandydatow(gotowe)
        return (f"Dodano {dodane}, duplikatów {len(gotowe) - dodane}, łącznie {len(self.kandydaci)}"
                f"/{self.kontekst.ile_kandydatow}."
                + ("\nOdrzucone:\n" + "\n".join(odrzucone) if odrzucone else ""))

    def _firma(self, arg: dict) -> Firma | str:
        if pid := arg.get("place_id"):
            if pid not in self.miejsca:
                return "nieznane place_id — tylko z wyników szukaj_miejsca w tym przebiegu"
            m, zrodlo = self.miejsca[pid]
            return Firma(nazwa=m.nazwa, www=m.www, adres=m.adres, telefon=m.telefon, place_id=pid,
                         zrodlo=zrodlo, zrodlo_url=f"https://www.google.com/maps/place/?q=place_id:{pid}")
        nazwa, url = arg.get("nazwa", "").strip(), arg.get("zrodlo_url", "")
        if not nazwa or url not in self.strony:
            return "podaj nazwa i zrodlo_url strony pobranej w tym przebiegu"
        rdzen = " ".join(_slowa(nazwa).split()[:2])
        if rdzen not in _slowa(self.strony[url]):
            return f"nazwa ({rdzen!r}) nie występuje na stronie {url}"
        return Firma(nazwa=nazwa, www=arg.get("www"), zrodlo=f"pobierz:{url}", zrodlo_url=url)

    def zapisz_kandydatow(self, firmy: list[Firma]) -> int:
        dodane = 0
        for f in firmy:
            klucze = {k for k in (f.place_id, _domena(f.www), _slowa(f.nazwa)) if k}
            if klucze & self._klucze:
                continue
            self._klucze |= klucze
            self.kandydaci.append(f)
            dodane += 1
            self.loguj(typ="kandydat", nazwa=f.nazwa, www=f.www, zrodlo=f.zrodlo, zrodlo_url=f.zrodlo_url)
        with open(self.katalog / "kandydaci.csv", "w", encoding="utf-8-sig", newline="") as plik:
            w = csv.DictWriter(plik, fieldnames=list(Firma.model_fields))
            w.writeheader()
            w.writerows(f.model_dump() for f in self.kandydaci)
        return dodane

    # --- pętla ---

    def wykonaj(self, w: Wywolanie) -> tuple[str, str, bool]:
        funkcja = getattr(self, f"t_{w.nazwa}", None)
        try:
            if funkcja is None:
                raise ValueError(f"nieznane narzędzie {w.nazwa}")
            if w.argumenty is None:
                raise ValueError("argumenty nie są poprawnym JSON-em")
            return w.id, funkcja(**w.argumenty), False
        except Exception as e:  # błąd narzędzia wraca do modelu, nie przerywa przebiegu
            self.loguj(typ="blad", narzedzie=w.nazwa, argumenty=w.argumenty, blad=f"{type(e).__name__}: {e}")
            return w.id, f"{type(e).__name__}: {e}", True

    def uruchom(self) -> list[Firma]:
        k, p, cel = self.kontekst, self.profil, self.kontekst.ile_kandydatow
        model = p.modele["odkrywanie"]
        system = SYSTEM.format(ile=cel, kogo=k.kogo_szukamy.strip(), obszar=k.obszar,
                               produkt=k.produkt.nazwa, problem=k.produkt.problem.strip(),
                               lokalizacje=", ".join(p.lokalizacje), frazy=", ".join(p.frazy_miejsca))
        self.loguj(typ="start", model=model, cel=cel)
        rozmowa = Rozmowa(model, system, NARZEDZIA)
        tekst, wywolania = rozmowa.krok(tekst="Zaczynaj.")
        ponaglono = False
        for krok in range(MAX_KROKOW):
            if tekst:
                self.loguj(typ="model", krok=krok, tekst=tekst)
            if not wywolania:
                if len(self.kandydaci) >= cel or ponaglono:
                    break
                ponaglono = True
                tekst, wywolania = rozmowa.krok(tekst=f"Masz {len(self.kandydaci)}/{cel}. Szukaj dalej "
                                                      "innymi frazami lub lokalizacjami, jeśli masz pomysły.")
                continue
            wyniki = [self.wykonaj(w) for w in wywolania]
            if len(self.kandydaci) >= cel:
                break
            tekst, wywolania = rozmowa.krok(wyniki=wyniki)
        self.loguj(typ="koniec", kandydatow=len(self.kandydaci), krokow=krok + 1)
        return self.kandydaci


def main(argv: list[str]) -> None:
    if not argv:
        sys.exit("Użycie: python -m radar.agent zlecenia/<nazwa>")
    katalog = Path(argv[0])
    kandydaci = Odkrywanie(katalog, wczytaj_kontekst(katalog), wczytaj_profil(katalog)).uruchom()
    print(f"{len(kandydaci)} kandydatów -> {katalog / 'kandydaci.csv'}, log: {katalog / 'log.jsonl'}")


if __name__ == "__main__":
    main(sys.argv[1:])
