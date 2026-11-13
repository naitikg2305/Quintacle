"""A small, deterministic place-name table for TEXT (2026-11-11).

photo_place._CONTINENTS already maps every country (and common variants) to
its continent, but nothing knew a city's country — so a trip plan saved
straight from a drop ("VIENNA, AUSTRIA | MAY 2027 ...") with no hand-typed
`fields.destinations` never joined the place graph. This module adds:

- CITIES: well-known travel cities → their country (canonical names, the
  same spelling photo geocoding produces for the big ones), curated by hand.
  Deliberately NOT exhaustive: a city missing here just isn't linked from
  free text (the user can still type it into Destinations); a WRONG link is
  worse than a missing one.
- find_places(text): every city / country NAMED in the text, conservatively:
  whole words, must start with a capital letter (so "nice weather" never
  reads as Nice — and Nice isn't listed anyway), ambiguous everyday words /
  first names / US states excluded, and a name right after "from" / "out of"
  / "leaving" (the departure point of a trip, not a destination) skipped.

No model call anywhere. Used by place_graph (derived destinations for
Fun/Travel/Planned + Bucket List notes) and the drop's bucket-list gate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

# city -> country. Countries spelled the way photo_place._CONTINENTS lists them.
_CITIES_BY_COUNTRY: dict[str, list[str]] = {
    # Europe
    "Austria": ["Vienna", "Wien", "Salzburg", "Innsbruck", "Graz", "Hallstatt", "Linz"],
    "Germany": ["Berlin", "Munich", "München", "Hamburg", "Frankfurt", "Cologne", "Köln", "Dresden",
                "Düsseldorf", "Stuttgart", "Heidelberg", "Nuremberg", "Leipzig"],
    "Switzerland": ["Zurich", "Zürich", "Geneva", "Lucerne", "Interlaken", "Zermatt", "Basel", "Lausanne"],
    "France": ["Paris", "Lyon", "Marseille", "Bordeaux", "Strasbourg", "Toulouse", "Cannes", "Chamonix"],
    "Italy": ["Rome", "Milan", "Venice", "Florence", "Naples", "Turin", "Bologna", "Pisa", "Verona",
              "Siena", "Sorrento", "Positano", "Amalfi", "Palermo"],
    "Spain": ["Madrid", "Barcelona", "Seville", "Valencia", "Granada", "Malaga", "Málaga", "Bilbao",
              "Ibiza", "San Sebastian", "San Sebastián"],
    "Portugal": ["Lisbon", "Porto", "Sintra", "Lagos", "Funchal"],
    "Netherlands": ["Amsterdam", "Rotterdam", "Utrecht", "The Hague"],
    "Belgium": ["Brussels", "Bruges", "Antwerp", "Ghent"],
    "United Kingdom": ["London", "Edinburgh", "Manchester", "Liverpool", "Glasgow", "Oxford", "Cambridge",
                       "Belfast", "Cardiff"],
    "Ireland": ["Dublin", "Galway"],
    "Czechia": ["Prague", "Brno", "Cesky Krumlov", "Český Krumlov"],
    "Hungary": ["Budapest"],
    "Poland": ["Warsaw", "Krakow", "Kraków", "Gdansk", "Gdańsk", "Wroclaw", "Wrocław"],
    "Slovakia": ["Bratislava"],
    "Slovenia": ["Ljubljana", "Bled"],
    "Croatia": ["Zagreb", "Dubrovnik", "Zadar", "Hvar"],
    "Greece": ["Athens", "Santorini", "Mykonos", "Thessaloniki", "Crete"],
    "Denmark": ["Copenhagen"],
    "Sweden": ["Stockholm", "Gothenburg"],
    "Norway": ["Oslo", "Bergen", "Tromsø", "Tromso"],
    "Finland": ["Helsinki", "Rovaniemi"],
    "Iceland": ["Reykjavik", "Reykjavík"],
    "Estonia": ["Tallinn"],
    "Latvia": ["Riga"],
    "Lithuania": ["Vilnius"],
    "Romania": ["Bucharest"],
    "Bulgaria": ["Sofia"],
    "Serbia": ["Belgrade"],
    "Montenegro": ["Kotor"],
    "Malta": ["Valletta"],
    "Russia": ["Moscow", "St Petersburg", "Saint Petersburg"],
    "Turkey": ["Istanbul", "Cappadocia", "Antalya", "Ankara"],
    # Asia
    "Japan": ["Tokyo", "Kyoto", "Osaka", "Nara", "Hiroshima", "Sapporo", "Hakone", "Nikko", "Fukuoka",
              "Yokohama", "Kanazawa", "Okinawa"],
    "South Korea": ["Seoul", "Busan", "Jeju"],
    "China": ["Beijing", "Shanghai", "Xi'an", "Chengdu", "Guilin", "Shenzhen", "Guangzhou"],
    "Hong Kong": ["Kowloon"],
    "Taiwan": ["Taipei"],
    "Thailand": ["Bangkok", "Chiang Mai", "Phuket", "Krabi"],
    "Vietnam": ["Hanoi", "Ho Chi Minh City", "Saigon", "Hoi An", "Da Nang", "Ha Long Bay"],
    "Cambodia": ["Siem Reap", "Phnom Penh"],
    "Indonesia": ["Bali", "Jakarta", "Ubud", "Yogyakarta"],
    "Malaysia": ["Kuala Lumpur", "Penang"],
    "Philippines": ["Manila", "Palawan", "Cebu"],
    "India": ["Delhi", "New Delhi", "Mumbai", "Bangalore", "Bengaluru", "Jaipur", "Agra", "Goa", "Kolkata",
              "Chennai", "Hyderabad", "Udaipur", "Varanasi", "Pune", "Rishikesh"],
    "Nepal": ["Kathmandu", "Pokhara"],
    "Sri Lanka": ["Colombo", "Kandy"],
    "United Arab Emirates": ["Dubai", "Abu Dhabi"],
    "Qatar": ["Doha"],
    "Israel": ["Jerusalem", "Tel Aviv"],
    "Jordan": ["Petra", "Amman"],
    "Maldives": [],
    # Africa
    "Egypt": ["Cairo", "Luxor", "Giza", "Aswan"],
    "Morocco": ["Marrakech", "Marrakesh", "Fes", "Fez", "Casablanca", "Chefchaouen"],
    "South Africa": ["Cape Town", "Johannesburg"],
    "Kenya": ["Nairobi"],
    "Tanzania": ["Zanzibar", "Kilimanjaro"],
    # North America
    "United States": ["New York", "New York City", "NYC", "Los Angeles", "San Francisco", "Chicago",
                      "Seattle", "Boston", "Miami", "Las Vegas", "New Orleans", "Honolulu", "Denver",
                      "Nashville", "San Diego", "Philadelphia", "Atlanta", "Yosemite", "Anchorage"],
    "Canada": ["Toronto", "Vancouver", "Montreal", "Montréal", "Quebec City", "Banff", "Calgary", "Ottawa"],
    "Mexico": ["Mexico City", "Cancun", "Cancún", "Tulum", "Oaxaca", "Playa del Carmen"],
    "Costa Rica": ["San José"],
    "Cuba": ["Havana"],
    # South America
    "Peru": ["Lima", "Cusco", "Cuzco", "Machu Picchu"],
    "Argentina": ["Buenos Aires", "Mendoza", "Patagonia"],
    "Brazil": ["Rio de Janeiro", "Sao Paulo", "São Paulo"],
    "Chile": ["Santiago"],
    "Colombia": ["Bogota", "Bogotá", "Medellin", "Medellín", "Cartagena"],
    "Ecuador": ["Quito", "Galapagos", "Galápagos"],
    # Oceania
    "Australia": ["Sydney", "Melbourne", "Brisbane", "Perth", "Cairns", "Adelaide"],
    "New Zealand": ["Auckland", "Queenstown", "Wellington", "Christchurch", "Rotorua"],
}

CITIES: dict[str, str] = {city: country for country, cities in _CITIES_BY_COUNTRY.items() for city in cities}

# Alternate spellings → the one name the graph uses, so "Wien" and "Vienna"
# land on the same node.
_CITY_CANON = {
    "Wien": "Vienna", "München": "Munich", "Köln": "Cologne", "Zürich": "Zurich", "Málaga": "Malaga",
    "San Sebastián": "San Sebastian", "Český Krumlov": "Cesky Krumlov", "Kraków": "Krakow",
    "Gdańsk": "Gdansk", "Wrocław": "Wroclaw", "Tromso": "Tromsø", "Reykjavík": "Reykjavik",
    "Saint Petersburg": "St Petersburg", "Saigon": "Ho Chi Minh City", "Bengaluru": "Bangalore",
    "Marrakesh": "Marrakech", "Fez": "Fes", "NYC": "New York", "New York City": "New York",
    "Montréal": "Montreal", "Cancún": "Cancun", "Cuzco": "Cusco", "São Paulo": "Sao Paulo",
    "Bogotá": "Bogota", "Medellín": "Medellin", "Galápagos": "Galapagos",
}

# Country variants → the canonical country name (one graph node per country).
_COUNTRY_CANON = {
    "holland": "Netherlands", "the netherlands": "Netherlands",
    "usa": "United States", "u.s.a.": "United States", "united states of america": "United States",
    "u.s.": "United States",
    "uk": "United Kingdom", "great britain": "United Kingdom", "britain": "United Kingdom",
    "czech republic": "Czechia", "türkiye": "Turkey", "turkiye": "Turkey", "viet nam": "Vietnam",
    "burma": "Myanmar", "republic of korea": "South Korea", "korea": "South Korea",
    "republic of ireland": "Ireland", "aotearoa": "New Zealand",
}

# Names that are also everyday words, first names or US states — never read
# from free text (a hand-typed Destinations field still accepts them).
_AMBIGUOUS = {
    "us", "u.s.", "america", "georgia", "jordan", "chad", "jersey", "turkey", "guinea", "car", "niger",
    "dominica", "grenada", "holland", "macao", "prc", "drc", "saint martin", "saint helena",
    "sofia", "petra", "lagos", "santiago", "perth", "cambridge", "oxford", "patagonia",
}

_ORIGIN_RE = re.compile(r"(?:\bfrom|\bout\s+of|\bleaving|\bdepart(?:ing|s)?(?:\s+from)?)\s+$", re.IGNORECASE)
# 2026-11-13 (owner, T2 NYC drop): "the Bronx's real Little Italy" listed
# Italy as a destination. A place name inside a neighborhood name (Little
# Italy, Little India, Little Havana, Little Tokyo) is not that place.
_NEIGHBORHOOD_BEFORE_RE = re.compile(r"\bLittle\s+$")
# 2026-11-13 (owner, T1 Austria drop): a city passed THROUGH is not a place
# visited. A mention right after "via" / "change(s) … " / "connecting in" /
# "layover in" / "stopover in", or one in the middle of a flight chain
# ("… to Frankfurt (FRA) to …"), doesn't count. The city still counts when
# it is named any other way elsewhere in the text.
_TRANSIT_BEFORE_RE = re.compile(
    r"(?:\bvia|\bchanges?\b[^.\n]{0,15}|\bconnect(?:ing|ion)?(?:\s+(?:in|at))?|\blayover(?:\s+(?:in|at))?|\bstopover(?:\s+(?:in|at))?)\s+$",
    re.IGNORECASE,
)
# 2026-11-13 (owner, Brazil drop): "connect once in the US (Miami, Atlanta,
# Houston or New York)" -- every city in a connection list is passed through,
# not visited. Reaches back to the nearest connection word in the same
# sentence (a ; or . ends it); a "to"/"into"/"then" after that word means the
# city is where the trip goes ("via Frankfurt to Vienna" keeps Vienna).
_TRANSIT_LIST_RE = re.compile(
    r"\b(?:via|connect(?:s|ing|ion)?|layovers?|stopovers?|change\s+planes)\b(?P<rest>[^.!?;\n]*)$",
    re.IGNORECASE,
)
_ONWARD_RE = re.compile(r"\b(?:to|into|then)\b", re.IGNORECASE)
# 2026-11-13 (owner, Brazil drop, chose the broad rule): "(like Budapest)"
# compares; a place right after like / such as / similar to / compared to is
# not a place on this trip. Owner accepted that "beach towns like Paraty"
# drops Paraty too.
_COMPARE_BEFORE_RE = re.compile(r"\b(?:like|such\s+as|similar\s+to|compared\s+to)\s+(?:your\s+)?$", re.IGNORECASE)
_CHAIN_BEFORE_RE = re.compile(r"\)\s*(?:to|->|→|-)\s+$")
_CHAIN_AFTER_RE = re.compile(r"^\s*\([A-Z]{3}\)\s*(?:to|->|→|-)\s")


@dataclass(frozen=True)
class PlaceMention:
    city: str | None
    country: str | None
    continent: str | None


def canonical_country(name: str) -> str | None:
    """A country name/variant → its canonical spelling, or None if it isn't a country."""
    from .nodes.kb.photo_place import _CONTINENTS, continent_for

    if not continent_for(name):
        return None
    alias = _COUNTRY_CANON.get(name.strip().lower())
    if alias:
        return alias
    low = name.strip().lower()
    for names in _CONTINENTS.values():
        for n in names:
            if n.lower() == low:
                return n
    return name.strip()


def canonical_city(name: str) -> tuple[str, str] | None:
    """A known city name/variant → (canonical city, country), else None."""
    low = name.strip().lower()
    for city, country in CITIES.items():
        if city.lower() == low:
            return _CITY_CANON.get(city, city), country
    return None


def continent_name(token: str) -> str | None:
    from .nodes.kb.photo_place import _CONTINENTS

    low = token.strip().lower()
    for name in _CONTINENTS:
        if name.lower() == low:
            return name
    return None


@lru_cache(maxsize=1)
def _names_regex() -> tuple[re.Pattern, dict[str, tuple[str, str]]]:
    from .nodes.kb.photo_place import _CONTINENTS

    lookup: dict[str, tuple[str, str]] = {}
    for city, country in CITIES.items():
        if city.lower() not in _AMBIGUOUS:
            lookup[city.lower()] = ("city", city)
    for names in _CONTINENTS.values():
        for n in names:
            if n.lower() in _AMBIGUOUS or len(n) <= 2:
                continue
            lookup.setdefault(n.lower(), ("country", n))
    alts = sorted(lookup, key=len, reverse=True)
    pattern = re.compile(r"(?<![\w])(" + "|".join(re.escape(a) for a in alts) + r")(?![\w])", re.IGNORECASE)
    return pattern, lookup


def find_places(text: str) -> list[PlaceMention]:
    """Every city / country NAMED in `text`, in order of first mention,
    de-duplicated. A city carries its country + continent; a country its
    continent. Departure points ("from Boston") are skipped."""
    from .nodes.kb.photo_place import continent_for

    if not text:
        return []
    pattern, lookup = _names_regex()
    out: list[PlaceMention] = []
    seen: set[tuple] = set()
    for m in pattern.finditer(text):
        word = m.group(1)
        if not word[0].isupper():
            continue
        if _ORIGIN_RE.search(text[max(0, m.start() - 20): m.start()]):
            continue
        if _NEIGHBORHOOD_BEFORE_RE.search(text[max(0, m.start() - 10): m.start()]):
            continue
        if _COMPARE_BEFORE_RE.search(text[max(0, m.start() - 20): m.start()]):
            continue
        kind, name = lookup[word.lower()]
        if kind == "city":
            before, after = text[max(0, m.start() - 30): m.start()], text[m.end(): m.end() + 12]
            if _TRANSIT_BEFORE_RE.search(before) or (_CHAIN_BEFORE_RE.search(before) and _CHAIN_AFTER_RE.match(after)):
                continue
            transit = _TRANSIT_LIST_RE.search(text[max(0, m.start() - 120): m.start()])
            if transit and not _ONWARD_RE.search(transit.group("rest")):
                continue
            city, country = canonical_city(name) or (name, None)
            mention = PlaceMention(city, country, continent_for(country) if country else None)
        else:
            country = canonical_country(name) or name
            mention = PlaceMention(None, country, continent_for(country))
        key = (mention.city, mention.country)
        if key not in seen:
            seen.add(key)
            out.append(mention)
    return out
