"""Wywołania modeli. Model zapisujemy jako "dostawca:model", np.

    anthropic:claude-opus-5
    hermes:upstage/solar-pro4:free     # lokalne proxy Hermesa (`hermes proxy start`), bez klucza API

Dostawcy inni niż anthropic mówią API zgodnym z OpenAI (chat/completions).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import TypeVar

import anthropic
import httpx
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# nazwa -> (base_url, zmienna z kluczem API lub None)
DOSTAWCY_OPENAI = {
    "hermes": ("http://127.0.0.1:8645/v1", None),  # proxy dokleja poświadczenia Nous Portal
}


def _rozbij(model: str) -> tuple[str, str]:
    dostawca, _, nazwa = model.partition(":")
    if not nazwa or (dostawca != "anthropic" and dostawca not in DOSTAWCY_OPENAI):
        raise ValueError(f"Nieznany model {model!r}; oczekiwano 'dostawca:model', dostawcy: "
                         f"anthropic, {', '.join(DOSTAWCY_OPENAI)}")
    return dostawca, nazwa


def _openai(dostawca: str, cialo: dict) -> dict:
    """POST chat/completions; zwraca choices[0]. Ponawia 429 (darmowe modele)."""
    url, klucz_env = DOSTAWCY_OPENAI[dostawca]
    klucz = os.environ[klucz_env] if klucz_env else "brak"
    for proba in range(4):
        odp = httpx.post(f"{url}/chat/completions", headers={"Authorization": f"Bearer {klucz}"},
                         json=cialo, timeout=600)
        if odp.status_code != 429 or proba == 3:
            break
        time.sleep(float(odp.headers.get("retry-after", 30)))
    if odp.is_error:  # treść błędu z proxy/dostawcy trafia do logu przebiegu
        raise RuntimeError(f"{dostawca}:{cialo['model']}: HTTP {odp.status_code}: {odp.text[:500]}")
    wybor = odp.json()["choices"][0]
    if wybor["finish_reason"] not in ("stop", "tool_calls"):
        raise RuntimeError(f"{dostawca}:{cialo['model']}: odpowiedź przerwana, "
                           f"finish_reason={wybor['finish_reason']}")
    return wybor


def json_wg_schematu(model: str, prompt: str, schemat: type[T]) -> T:
    """Jedno zapytanie, odpowiedź zwalidowana schematem Pydantic."""
    dostawca, nazwa = _rozbij(model)
    if dostawca == "anthropic":
        odp = anthropic.Anthropic().messages.parse(
            model=nazwa,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            messages=[{"role": "user", "content": prompt}],
            output_format=schemat,
        )
        if odp.stop_reason != "end_turn" or odp.parsed_output is None:
            raise RuntimeError(f"{model}: odpowiedź przerwana, stop_reason={odp.stop_reason}")
        return odp.parsed_output

    wybor = _openai(dostawca, {
        "model": nazwa,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schemat.__name__, "schema": schemat.model_json_schema()},
        },
    })
    tresc = wybor["message"]["content"].strip()
    # część modeli owija JSON w ```json ... ``` mimo response_format
    tresc = tresc.removeprefix("```json").removeprefix("```").removesuffix("```")
    return schemat.model_validate(json.loads(tresc))


@dataclass
class Narzedzie:
    nazwa: str
    opis: str
    parametry: dict  # JSON Schema argumentów


@dataclass
class Wywolanie:
    id: str
    nazwa: str
    argumenty: dict | None  # None = model podał niepoprawny JSON


class Rozmowa:
    """Rozmowa z function calling. Historia trzymana w formacie dostawcy, na zewnątrz jeden interfejs:

        r = Rozmowa(model, system, narzedzia)
        tekst, wywolania = r.krok(tekst="zadanie")
        tekst, wywolania = r.krok(wyniki=[(wywolanie.id, "wynik", czy_blad)])
    """

    def __init__(self, model: str, system: str, narzedzia: list[Narzedzie]):
        self.dostawca, self.nazwa = _rozbij(model)
        self.system = system
        self.narzedzia = narzedzia
        self.wiadomosci: list = [] if self.dostawca == "anthropic" else [{"role": "system", "content": system}]

    def krok(self, tekst: str | None = None,
             wyniki: list[tuple[str, str, bool]] | None = None) -> tuple[str, list[Wywolanie]]:
        if self.dostawca == "anthropic":
            return self._krok_anthropic(tekst, wyniki or [])
        return self._krok_openai(tekst, wyniki or [])

    def _krok_anthropic(self, tekst, wyniki):
        tresc = [{"type": "tool_result", "tool_use_id": id_, "content": w, "is_error": blad}
                 for id_, w, blad in wyniki]
        if tekst:
            tresc.append({"type": "text", "text": tekst})
        self.wiadomosci.append({"role": "user", "content": tresc})
        odp = anthropic.Anthropic().messages.create(
            model=self.nazwa,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=self.system,
            tools=[{"name": n.nazwa, "description": n.opis, "input_schema": n.parametry}
                   for n in self.narzedzia],
            messages=self.wiadomosci,
        )
        if odp.stop_reason not in ("end_turn", "tool_use"):
            raise RuntimeError(f"anthropic:{self.nazwa}: stop_reason={odp.stop_reason}")
        self.wiadomosci.append({"role": "assistant", "content": odp.content})
        return (
            "".join(b.text for b in odp.content if b.type == "text"),
            [Wywolanie(b.id, b.name, b.input) for b in odp.content if b.type == "tool_use"],
        )

    def _krok_openai(self, tekst, wyniki):
        self.wiadomosci += [{"role": "tool", "tool_call_id": id_, "content": ("BŁĄD: " if blad else "") + w}
                            for id_, w, blad in wyniki]
        if tekst:
            self.wiadomosci.append({"role": "user", "content": tekst})
        wybor = _openai(self.dostawca, {
            "model": self.nazwa,
            "messages": self.wiadomosci,
            "tools": [{"type": "function", "function": {"name": n.nazwa, "description": n.opis,
                                                        "parameters": n.parametry}}
                      for n in self.narzedzia],
        })
        msg = wybor["message"]
        self.wiadomosci.append({"role": "assistant", "content": msg.get("content") or "",
                                **({"tool_calls": msg["tool_calls"]} if msg.get("tool_calls") else {})})
        wywolania = []
        for w in msg.get("tool_calls") or []:
            try:
                argumenty = json.loads(w["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                argumenty = None
            wywolania.append(Wywolanie(w["id"], w["function"]["name"], argumenty))
        return msg.get("content") or "", wywolania
