"""Proper-noun generation: person names and place names.

Pure-grammar word lists (era-flavored) are the base -- this must keep
working with Ollama offline. When config.LLM_FILL_NAMES is on and Ollama is
reachable (llm.available()), we ask the local model for a name instead,
since it's cheap and produces far more varied, specific results than a
fixed word list ever will; any failure (timeout, bad output) falls straight
back to the grammar with no visible error.
"""

import random

import config
import llm
from eras import ERAS_BY_ID

_GIVEN_DUTCH = ["Jan", "Pieter", "Willem", "Cornelis", "Hendrick", "Anneke", "Griet", "Marritje", "Trijntje", "Aeltje"]
_GIVEN_ENGLISH = ["William", "John", "Thomas", "Samuel", "Elizabeth", "Margaret", "Abigail", "Josiah", "Nathaniel", "Prudence"]
_GIVEN_19C = ["Patrick", "Seamus", "Bridget", "Katharina", "Heinrich", "Mary", "Michael", "Anna", "Cornelius", "Delia"]
_GIVEN_20C = ["Rose", "Sal", "Frank", "Dorothy", "Irving", "Ruth", "Vincent", "Gloria", "Moe", "Sadie"]

_SURNAME_DUTCH = ["Van der Berg", "De Groot", "Bogaert", "Van Dyck", "Kuyper", "Stuyvesant", "Verplanck", "Rutgers"]
_SURNAME_ENGLISH = ["Beekman", "Livingston", "Morris", "Hamilton", "Bayard", "Fish", "Roosevelt", "Whitfield"]
_SURNAME_19C = ["O'Malley", "Schmidt", "Muller", "Fitzgerald", "Costello", "Weber", "Doyle", "Kessler"]
_SURNAME_20C = ["Russo", "Cohen", "Bianchi", "Kowalski", "Moretti", "Feldman", "Lombardi", "Sullivan"]

_NAMES_BY_ERA = {
    "dutch_colonial": (_GIVEN_DUTCH, _SURNAME_DUTCH),
    "english_colonial": (_GIVEN_ENGLISH, _SURNAME_ENGLISH),
    "early_republic": (_GIVEN_ENGLISH, _SURNAME_ENGLISH),
    "antebellum": (_GIVEN_19C, _SURNAME_19C),
    "gilded_age": (_GIVEN_19C, _SURNAME_19C),
    "progressive": (_GIVEN_20C, _SURNAME_20C),
    "prohibition": (_GIVEN_20C, _SURNAME_20C),
    "depression_war": (_GIVEN_20C, _SURNAME_20C),
}

_ADJECTIVES = ["Gilded", "Broken", "Crooked", "Copper", "Weeping", "Rusty", "Silver", "Drowsy", "Iron", "Salt-worn"]
_ANIMALS = ["Sparrow", "Anchor", "Fox", "Gull", "Stag", "Eel", "Raven", "Hare"]
_SAINTS_VIRTUES = ["St. Nicholas", "St. Andrew", "the Redeemer", "Grace", "the Good Shepherd", "St. Brigid"]
_PRESS_WORDS = ["Herald", "Ledger", "Courier", "Gazette", "Tribune", "Sentinel"]
_STREETS = ["Mulberry Street", "Cherry Street", "Orchard Street", "Bowery Lane", "Water Street", "Delancey Street"]
_PRODUCTS = ["Ironworks", "Textile", "Foundry", "Glassworks", "Tannery", "Print"]

_NAMING_STYLE = {
    "Tavern/Bar": "tavern", "Speakeasy": "tavern",
    "Restaurant": "surname_possessive", "General Store/Shop": "surname_possessive",
    "Market": "surname_possessive", "Department Store": "surname_possessive",
    "Bank/Counting House": "firm", "Shipyard/Dock/Warehouse": "firm",
    "Factory/Mill": "works",
    "Church/House of Worship": "civic", "Park/Public Square": "civic",
    "Government/Civic Building": "civic", "School": "civic",
    "Theater/Hall": "tavern", "Social/Fraternal Club": "tavern",
    "Hotel/Boarding House": "surname_possessive",
    "Newspaper/Print Shop": "press",
    "Tenement/Residence": "address",
}


def _names_for_era(era_id: str):
    return _NAMES_BY_ERA.get(era_id, (_GIVEN_ENGLISH, _SURNAME_ENGLISH))


def _grammar_figure_name(era_id: str, rng: random.Random) -> str:
    givens, surnames = _names_for_era(era_id)
    return f"{rng.choice(givens)} {rng.choice(surnames)}"


def _grammar_place_name(place_type: str, domain: str, founder_surname: str, rng: random.Random) -> str:
    style = _NAMING_STYLE.get(place_type, "surname_possessive")
    if style == "tavern":
        return f"The {rng.choice(_ADJECTIVES)} {rng.choice(_ANIMALS)}"
    if style == "firm":
        return f"{founder_surname} & Sons"
    if style == "works":
        return f"{founder_surname} {rng.choice(_PRODUCTS)} Works"
    if style == "civic":
        return f"{rng.choice(_SAINTS_VIRTUES)}" if "Church" in place_type else f"{founder_surname} {place_type.split('/')[0]}"
    if style == "press":
        # domain may itself start with "the" (e.g. "the vote") -- strip it
        # before title-casing so this doesn't produce "The The Vote Sentinel".
        domain_word = domain[4:] if domain.lower().startswith("the ") else domain
        return f"The {domain_word.title()} {rng.choice(_PRESS_WORDS)}"
    if style == "address":
        return f"{rng.randint(1, 400)} {rng.choice(_STREETS)}"
    return f"{founder_surname}'s"


def figure_name(era_id: str, role: str, rng: random.Random) -> str:
    if config.LLM_FILL_NAMES and llm.available():
        era = ERAS_BY_ID.get(era_id)
        try:
            prompt = (
                f"Give one plausible full person name (first and last) for a {role} "
                f"living in New York City during {era.name if era else era_id} "
                f"(roughly {era.start_year}-{era.end_year})." if era else
                f"Give one plausible full person name for a {role} in old New York City."
            )
            prompt += " Reply with ONLY the name, nothing else -- no titles, no explanation."
            name = llm.complete(prompt, temperature=0.9).strip().strip('"').strip(".")
            if name and "\n" not in name and 3 <= len(name) <= 50:
                return name
        except Exception:
            pass
    return _grammar_figure_name(era_id, rng)


def place_name(place_type: str, domain: str, founder_surname: str, era_id: str, rng: random.Random) -> str:
    if config.LLM_FILL_NAMES and llm.available():
        era = ERAS_BY_ID.get(era_id)
        try:
            prompt = (
                f"Give one short, period-appropriate business/place name for a "
                f"{place_type} in New York City around {era.start_year if era else '1800'}, "
                f"founded by someone surnamed {founder_surname}, thematically associated "
                f"with \"{domain}\". Reply with ONLY the name, nothing else."
            )
            name = llm.complete(prompt, temperature=0.95).strip().strip('"').strip(".")
            if name and "\n" not in name and 2 <= len(name) <= 60:
                return name
        except Exception:
            pass
    return _grammar_place_name(place_type, domain, founder_surname, rng)
