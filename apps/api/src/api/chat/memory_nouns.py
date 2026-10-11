"""장면 기억의 명사 토큰(구현 전 자리)."""

from collections.abc import Iterable

STOPWORDS: frozenset[str] = frozenset()


def rule_tokens(text: str) -> list[str]:
    return []


def episode_nouns(model_nouns: Iterable[str], title: str, detail: str) -> list[str]:
    return []
