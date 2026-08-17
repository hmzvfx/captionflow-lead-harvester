from __future__ import annotations

from dataclasses import dataclass
from itertools import product

NICHE_TERMS = {
    "fitness": ("coach fitness", "personal trainer", "fitness tips", "online coach", "nutrition coach", "musculation", "perte de poids"),
    "business": ("business coach", "entrepreneur", "business tips", "personal brand", "fondateur", "solopreneur"),
    "marketing": ("marketing coach", "content marketing", "growth marketing", "social media tips", "copywriting"),
    "coaching": ("coach en ligne", "consultant", "formateur", "mentor", "coaching business"),
    "real_estate": ("agent immobilier", "real estate coach", "immobilier conseils", "realtor tips"),
    "finance": ("finance creator", "personal finance", "investissement", "finance tips", "educateur financier"),
}

LANGUAGE_HINTS = {"fr": ("français", "france", "belgique", "quebec"), "en": ("english",), "nl": ("nederlands", "belgie")}


@dataclass
class QueryBatch:
    queries: list[str]
    next_offset: int


class QueryExpansionEngine:
    def __init__(self, niches: tuple[str, ...], languages: tuple[str, ...], creator_types: tuple[str, ...]):
        self.niches = niches
        self.languages = languages
        self.creator_types = creator_types

    def all_queries(self) -> list[str]:
        queries: list[str] = []
        for niche in self.niches:
            terms = NICHE_TERMS.get(niche, (niche.replace("_", " "),))
            for term in terms:
                queries.append(term)
                for lang in self.languages[:2]:
                    hints = LANGUAGE_HINTS.get(lang, ())
                    if hints:
                        queries.append(f"{term} {hints[0]}")
            for creator in self.creator_types[:3]:
                queries.append(f"{creator} {niche.replace('_', ' ')}")
        out: list[str] = []
        seen: set[str] = set()
        for query in queries:
            key = " ".join(query.lower().split())
            if key not in seen:
                seen.add(key)
                out.append(query.strip())
        return out

    def next_batch(self, offset: int, limit: int) -> QueryBatch:
        all_queries = self.all_queries()
        if not all_queries or limit <= 0:
            return QueryBatch([], offset)
        start = offset % len(all_queries)
        selected = [all_queries[(start + i) % len(all_queries)] for i in range(min(limit, len(all_queries)))]
        return QueryBatch(selected, (start + len(selected)) % len(all_queries))
