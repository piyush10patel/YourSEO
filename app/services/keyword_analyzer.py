"""Lightweight, dependency-free keyword analysis.

Not a replacement for a real SEO data provider (search volume, SERP data,
etc.) — it works purely from on-page text to surface what the page actually
emphasises: top unigrams/bigrams, their density, and how well a set of target
keywords are covered. That's enough signal for the agent to reason about
keyword gaps.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

# A compact English stop-word list — enough to filter the obvious noise
# without pulling in NLTK.
_STOPWORDS = frozenset(
    """
    a an and are as at be by for from has have he her his i in is it its of on
    or that the to was were will with you your our we they this these those but
    not no so if then than them their there here out up down over under about
    into more most some such only own same too very can just also any each few
    other all both because been being do does did doing how what when where who
    whom why which while
    """.split()
)

_WORD_RE = re.compile(r"[a-z][a-z'\-]+")


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _content_tokens(tokens: list[str]) -> list[str]:
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 2]


def _top(counter: Counter[str], total: int, n: int) -> list[dict[str, Any]]:
    return [
        {
            "term": term,
            "count": count,
            "density_pct": round(100 * count / total, 2) if total else 0.0,
        }
        for term, count in counter.most_common(n)
    ]


def analyze_keywords(
    text: str,
    *,
    target_keywords: list[str] | None = None,
    top_n: int = 15,
) -> dict[str, Any]:
    """Return a keyword profile for ``text``.

    Includes total/unique word counts, the top single-word and two-word
    keywords with density, and — if ``target_keywords`` is given — how often
    each appears (so the caller can spot under-served or missing terms).
    """
    tokens = _tokenize(text)
    total_words = len(tokens)
    content = _content_tokens(tokens)

    unigrams = Counter(content)
    bigrams = Counter(f"{content[i]} {content[i + 1]}" for i in range(len(content) - 1))

    result: dict[str, Any] = {
        "total_words": total_words,
        "unique_content_words": len(unigrams),
        "top_keywords": _top(unigrams, total_words, top_n),
        "top_phrases": _top(bigrams, total_words, top_n),
    }

    if target_keywords:
        haystack = " ".join(tokens)
        coverage = []
        for kw in target_keywords:
            kw_norm = kw.lower().strip()
            count = len(re.findall(rf"\b{re.escape(kw_norm)}\b", haystack))
            coverage.append(
                {
                    "keyword": kw,
                    "count": count,
                    "present": count > 0,
                    "density_pct": (
                        round(100 * count / total_words, 2) if total_words else 0.0
                    ),
                }
            )
        result["target_coverage"] = coverage

    return result
