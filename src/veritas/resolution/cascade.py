from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, process

from veritas.registry import Registry
from veritas.settings import Settings, get_settings


@dataclass
class ResolutionResult:
    canonical: str | None
    method: str
    confidence: float
    pending_ai: bool = False


class TestNameResolver:
    """Cost-ordered cascade: Exact → Fuzzy → NLP → Gemini(pending)."""

    def __init__(self, registry: Registry, settings: Settings | None = None):
        self.registry = registry
        self.settings = settings or get_settings()
        self._alias_choices = [a for a, _ in registry.all_alias_pairs()]
        self._nlp = None

    def resolve(self, raw_name: str | None) -> ResolutionResult:
        if not raw_name or not str(raw_name).strip():
            return ResolutionResult(None, "empty", 0.0)

        name = str(raw_name).strip()

        # A. Exact / registry (incl. learned Gemini hits)
        exact = self.registry.exact_lookup(name)
        if exact:
            return ResolutionResult(exact, "exact_registry", 1.0)

        # B. Fuzzy (rapidfuzz)
        fuzzy = self._fuzzy(name)
        if fuzzy:
            return fuzzy

        # C. NLP / token similarity (local mid-cost)
        nlp = self._nlp_match(name)
        if nlp:
            return nlp

        # D. Gemini last resort — mark pending; async worker resolves ≤24h
        return ResolutionResult(None, "pending_ai", 0.0, pending_ai=True)

    def _fuzzy(self, name: str) -> ResolutionResult | None:
        if not self._alias_choices:
            return None
        match = process.extractOne(
            name,
            self._alias_choices,
            scorer=fuzz.WRatio,
            score_cutoff=self.settings.fuzzy_match_threshold,
        )
        if not match:
            return None
        alias, score, _ = match
        canonical = self.registry.exact_lookup(alias) or alias
        return ResolutionResult(canonical, "fuzzy", float(score) / 100.0)

    def _nlp_match(self, name: str) -> ResolutionResult | None:
        """Lightweight token-overlap nearest neighbour (spaCy optional)."""
        tokens = _tokens(name)
        if not tokens:
            return None
        best_name = None
        best_score = 0.0
        for canonical in self.registry.all_canonical_names():
            score = _jaccard(tokens, _tokens(canonical))
            if score > best_score:
                best_score = score
                best_name = canonical
            for alias in (self.registry.test_meta(canonical).get("aliases") or []):
                score = _jaccard(tokens, _tokens(alias))
                if score > best_score:
                    best_score = score
                    best_name = canonical

        # Optional spaCy vector boost
        try:
            nlp = self._get_spacy()
            if nlp is not None:
                doc = nlp(name)
                if doc.vector_norm:
                    for canonical in self.registry.all_canonical_names():
                        other = nlp(canonical)
                        if other.vector_norm:
                            sim = float(doc.similarity(other))
                            if sim > best_score:
                                best_score = sim
                                best_name = canonical
        except Exception:
            pass

        if best_name and best_score >= self.settings.nlp_match_threshold:
            return ResolutionResult(best_name, "nlp", best_score)
        return None

    def _get_spacy(self):
        if self._nlp is False:
            return None
        if self._nlp is not None:
            return self._nlp
        try:
            import spacy

            self._nlp = spacy.load("en_core_web_sm")
            return self._nlp
        except Exception:
            self._nlp = False
            return None


def _tokens(text: str) -> set[str]:
    stop = {"the", "of", "and", "for", "a", "an", "to", "in", "on", "with", "test"}
    raw = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return {t for t in raw.split() if t and t not in stop}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
