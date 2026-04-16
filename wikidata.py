"""Consulta de Wikidata mediante SPARQL.

Wikidata devuelve datos ESTRUCTURADOS (fecha de nacimiento, ocupación,
nacionalidad, empleadores, etc.) que son ideales como contexto para el Q&A.
"""
import logging

import requests

logger = logging.getLogger(__name__)

ENDPOINT = "https://query.wikidata.org/sparql"
HEADERS = {
    "Accept": "application/sparql-results+json",
    "User-Agent": "OSINT-Telegram-Bot/1.0 (https://example.com)",
}

# SPARQL: busca una entidad humana (Q5) cuyo label case con `name` y
# trae sus propiedades más útiles. LIMIT 1 para quedarnos con el match
# más probable en el idioma pedido.
QUERY = """
SELECT ?person ?personLabel ?birth ?death ?occupationLabel
       ?countryLabel ?employerLabel ?genderLabel ?website
WHERE {
  ?person rdfs:label "%%NAME%%"@%%LANG%% ;
          wdt:P31 wd:Q5 .
  OPTIONAL { ?person wdt:P569 ?birth. }
  OPTIONAL { ?person wdt:P570 ?death. }
  OPTIONAL { ?person wdt:P106 ?occupation. }
  OPTIONAL { ?person wdt:P27  ?country. }
  OPTIONAL { ?person wdt:P108 ?employer. }
  OPTIONAL { ?person wdt:P21  ?gender. }
  OPTIONAL { ?person wdt:P856 ?website. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "%%LANG%%,en". }
}
LIMIT 20
"""


def search_wikidata(name: str, lang: str = "es") -> dict | None:
    """Devuelve un dict con datos estructurados o None."""
    if not name or len(name) > 120:
        return None

    # Sanea comillas para SPARQL.
    safe = name.replace('"', "").replace("\\", "")
    query = QUERY.replace("%%NAME%%", safe).replace("%%LANG%%", lang)

    try:
        r = requests.get(
            ENDPOINT,
            params={"query": query, "format": "json"},
            headers=HEADERS,
            timeout=15,
        )
        if r.status_code != 200:
            if lang != "en":
                return search_wikidata(name, "en")
            return None
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        logger.error("Error Wikidata: %s", exc)
        return None

    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        if lang != "en":
            return search_wikidata(name, "en")
        return None

    # Agrupa todas las filas en un único perfil (las OPTIONAL multiplican filas).
    first = bindings[0]
    qid_url = first.get("person", {}).get("value", "")
    person_label = first.get("personLabel", {}).get("value")

    def collect(field: str) -> list[str]:
        values = {b.get(field, {}).get("value") for b in bindings}
        return sorted(v for v in values if v)

    occupations = collect("occupationLabel")
    countries = collect("countryLabel")
    employers = collect("employerLabel")

    profile = {
        "label": person_label,
        "wikidata_url": qid_url,
        "birth": first.get("birth", {}).get("value", "").split("T")[0] or None,
        "death": first.get("death", {}).get("value", "").split("T")[0] or None,
        "gender": first.get("genderLabel", {}).get("value"),
        "website": first.get("website", {}).get("value"),
        "occupations": occupations[:10],
        "countries": countries[:5],
        "employers": employers[:10],
    }
    # Si absolutamente todo es None/vacío, devolvemos None.
    if not any([profile["birth"], profile["death"], occupations, countries, employers]):
        return None
    return profile
