"""매 턴 회상(자리만 있다)."""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Executable, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_window import MessageKey
from api.chat.prompt_builder import PromptNames
from api.core.sentry import capture_dependency_failure
from api.db.models.chat import ChatMessage

TAU = 0.60
MAX_INJECT_RECALL_CUE = 3


@dataclass(frozen=True)
class RecallQuery:
    user: frozenset[str]
    assistant: frozenset[str]
    time_cue: bool


@dataclass(frozen=True)
class RecallCandidate:
    id: str
    nouns: frozenset[str]
    importance: int
    end_turn: int
    snapshot: int


@dataclass(frozen=True)
class ScoredEpisode:
    id: str
    s: float
    r: float
    overlap: frozenset[str]
    end_turn: int
    snapshot: int


@dataclass(frozen=True)
class Recall:
    lines: str
    record: tuple[dict[str, Any], ...]


NO_RECALL = Recall("", ())


def recall_cue(text: str) -> bool:
    return False


def query_tokens(
    user_text: str, previous_assistant: str, *, episode_nouns: frozenset[str], names: Iterable[str]
) -> RecallQuery:
    return RecallQuery(frozenset(), frozenset(), False)


def score_episodes(rows: Sequence[RecallCandidate], query: RecallQuery, *, current_turn: int) -> list[ScoredEpisode]:
    return []


def select_injected(scored: Sequence[ScoredEpisode], *, recall_cue: bool) -> list[ScoredEpisode]:
    return []


def recall_line(title: str, detail: str, asserted_by: str) -> str:
    return ""


def _candidate_statement(room_id: uuid.UUID, cursor: MessageKey) -> Executable:
    return text("SELECT 1")


async def recall_for_turn(
    db: AsyncSession,
    *,
    room_id: uuid.UUID,
    cursor: MessageKey,
    history: Sequence[ChatMessage],
    window: Sequence[ChatMessage],
    user_content: str,
    names: PromptNames,
) -> Recall:
    del capture_dependency_failure
    return NO_RECALL
