"""요약 접기가 접은 대화 구간을 장면 기억으로 뽑는다(구현 전 자리)."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core.sentry import capture_dependency_failure as capture_dependency_failure
from api.chat.prompt_builder import MemoryEpisodeResult, PromptNames
from api.db.models import ChatMessage, PromptSection, PromptSet
from api.llm.client import LLMClient


@dataclass(frozen=True)
class EpisodeDraft:
    ordinal: int
    start_key: tuple[datetime, uuid.UUID]
    end_key: tuple[datetime, uuid.UUID]
    start_turn: int
    end_turn: int
    title: str
    detail: str
    nouns: list[str]
    keywords: list[str]
    evidence: list[str]
    asserted_by: str
    importance: int


def normalize_episodes(
    result: MemoryEpisodeResult, window: Sequence[ChatMessage], *, turns_before: int
) -> list[EpisodeDraft]:
    return []


async def extract_pending_episode(
    session_factory: async_sessionmaker[AsyncSession],
    llm_client: LLMClient,
    *,
    room_id: uuid.UUID,
    user_id: uuid.UUID,
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
    is_story_chat: bool,
    names: PromptNames,
) -> None:
    return None


async def _next_candidate(session: AsyncSession, room_id: uuid.UUID) -> None:
    return None


async def _lock_snapshot(session: AsyncSession, snapshot_id: uuid.UUID) -> bool:
    return False


async def _finish_claim(session: AsyncSession) -> bool:
    return False
