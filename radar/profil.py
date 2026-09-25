"""Generowanie profilu zlecenia z kontekstu. Uruchamiane raz na zlecenie.

    python -m radar.profil zlecenia/<nazwa> [--nadpisz]

Wynik: zlecenia/<nazwa>/profil.yaml — do ręcznej korekty przed dalszymi etapami.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import anthropic
import yaml
from pydantic import BaseModel

from radar.typy import Kontekst, PoleSchematu, Profil, Regula

MODEL_PROFILU = "claude-opus-5"

MODELE_DOMYSLNE = {
    "odkrywanie": "claude-opus-5",  # planowanie zapytań
    "trafnosc": "claude-haiku-4-5",  # ocena próbki wyników wyszukiwania
    "ekstrakcja": "claude-haiku-4-5",
    "zaczepka": "claude-opus-5",
}

PROMPT = """\
Przygotowujesz profil wyszukiwania i kwalifikacji potencjalnych klientów B2B.

KOGO SZUKAMY:
{kogo_szukamy}

CO SPRZEDAJEMY: {produkt_nazwa}
{produkt_opis}

JAKI PROBLEM TO ROZWIĄZUJE:
{produkt_problem}

OBSZAR: {obszar}
WIELKOŚĆ FIRMY: {pracownicy_min}–{pracownicy_max} pracowników

Zwróć:

lokalizacje — konkretne miejscowości (i dzielnice, jeśli to duże miasto) pokrywające obszar,
łącznie z przyległymi gminami, w których takie firmy realnie mają siedziby. Będą doklejane
do fraz przy wyszukiwaniu w Mapach Google.

frazy_miejsca — 8–15 krótkich fraz, jakimi takie firmy opisują się w Mapach Google
(kategorie, synonimy, warianty nazewnictwa). BEZ nazwy miejscowości.

frazy_web — 8–15 zapytań do wyszukiwarki nastawionych na LISTY firm, nie pojedyncze firmy:
katalogi branżowe, izby i stowarzyszenia, listy wystawców targowych, rankingi, członkowie
klastrów. Z nazwą obszaru tam, gdzie ma to sens.

pkd — kody PKD (format 52.29.C) typowe dla przeważającej działalności takich firm.

schemat — 6–12 faktów do wyciągnięcia ze strony WWW firmy. Tylko fakty, które da się
wskazać cytatem w tekście strony; nic, co wymaga domysłu. Nazwa: snake_case, ASCII.
Typ: tekst | liczba | tak_nie | lista. Opis: co dokładnie wyciągnąć i po jakich
sformułowaniach to rozpoznać. Zawsze uwzględnij liczbę pracowników (typ liczba).

reguly — punktacja liczona przez kod na podstawie faktów. Punktuj OZNAKI PROBLEMU, który
rozwiązuje produkt (skala i charakter zjawiska, które produkt usprawnia; brak rozwiązania,
które by go zastępowało), a nie samą przynależność do branży. Dodaj reguły ujemne:
firma poza widełkami wielkości, ma już podobne rozwiązanie, nie ma problemu.
Każda reguła: id (snake_case), fakt (nazwa z schematu), warunek, wartosc, punkty, uzasadnienie.
Warunki: "prawda" (fakt tak_nie = true), "wypelniony" (fakt znaleziony), ">=" / "<="
(fakt liczba, wartosc to próg), "zawiera" (fakt tekst/lista zawiera wartosc, bez względu
na wielkość liter). Punkty od -30 do +30; firma idealna ma ok. 100 pkt łącznie.
Uzasadnienie: jednym zdaniem, jak ten fakt wiąże się z problemem, który rozwiązuje produkt.

Pisz po polsku. Nic ogólnikowego — każda fraza i reguła ma być użyteczna dla tego zlecenia.
"""


class _Pole(PoleSchematu):
    nazwa: str


class _Regula(Regula):
    id: str


class _Szkic(BaseModel):
    lokalizacje: list[str]
    frazy_miejsca: list[str]
    frazy_web: list[str]
    pkd: list[str]
    schemat: list[_Pole]
    reguly: list[_Regula]


def generuj_profil(kontekst: Kontekst) -> Profil:
    tresc = PROMPT.format(
        kogo_szukamy=kontekst.kogo_szukamy,
        produkt_nazwa=kontekst.produkt.nazwa,
        produkt_opis=kontekst.produkt.opis,
        produkt_problem=kontekst.produkt.problem,
        obszar=kontekst.obszar,
        pracownicy_min=kontekst.pracownicy_min,
        pracownicy_max=kontekst.pracownicy_max,
    )
    odp = anthropic.Anthropic().messages.parse(
        model=MODEL_PROFILU,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        messages=[{"role": "user", "content": tresc}],
        output_format=_Szkic,
    )
    if odp.stop_reason != "end_turn" or odp.parsed_output is None:
        raise RuntimeError(f"Generowanie profilu przerwane: stop_reason={odp.stop_reason}")
    s = odp.parsed_output
    return Profil(
        lokalizacje=s.lokalizacje,
        frazy_miejsca=s.frazy_miejsca,
        frazy_web=s.frazy_web,
        pkd=s.pkd,
        schemat={p.nazwa: PoleSchematu(**p.model_dump(exclude={"nazwa"})) for p in s.schemat},
        reguly={r.id: Regula(**r.model_dump(exclude={"id"})) for r in s.reguly},
        modele=dict(MODELE_DOMYSLNE),
    )


def wczytaj_kontekst(katalog: Path) -> Kontekst:
    return Kontekst(**yaml.safe_load((katalog / "kontekst.yaml").read_text(encoding="utf-8")))


def wczytaj_profil(katalog: Path) -> Profil:
    return Profil(**yaml.safe_load((katalog / "profil.yaml").read_text(encoding="utf-8")))


def zapisz_profil(profil: Profil, katalog: Path) -> Path:
    sciezka = katalog / "profil.yaml"
    naglowek = (
        f"# Wygenerowano {date.today()} modelem {MODEL_PROFILU} z kontekst.yaml.\n"
        "# Plik do ręcznej korekty. Kolejne etapy czytają go bez zmian.\n\n"
    )
    tresc = yaml.safe_dump(profil.model_dump(), allow_unicode=True, sort_keys=False, width=100)
    sciezka.write_text(naglowek + tresc, encoding="utf-8")
    return sciezka


def main(argv: list[str]) -> None:
    if not argv or argv[0].startswith("-"):
        sys.exit("Użycie: python -m radar.profil zlecenia/<nazwa> [--nadpisz]")
    katalog = Path(argv[0])
    if (katalog / "profil.yaml").exists() and "--nadpisz" not in argv:
        sys.exit(f"{katalog / 'profil.yaml'} już istnieje (ręczne poprawki?). Użyj --nadpisz.")
    profil = generuj_profil(wczytaj_kontekst(katalog))
    print(f"Zapisano {zapisz_profil(profil, katalog)}")


if __name__ == "__main__":
    main(sys.argv[1:])
