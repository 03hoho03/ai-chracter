"""하네스가 앱 코드를 프로세스 안에서 부를 때 쓰는 공통 — DB 엔진, 방·레인·시작설정·이름 읽기, 레인별 프롬프트 세트, 갈래 설정,
앱 API 클라이언트.

레인은 방에서 읽는다(시작설정이 있으면 스토리, 없으면 캐릭터 — 앱의 레인 고르기와 같다). 생성·판정·요약 세트는 그 레인의 활성
세트를 읽는다 — 다른 레인의 세트로 조립하면 다른 작품 꼴의 문안이 실린다.

DB 는 언제나 `settings.database_url`(실행 명령의 `DATABASE_URL`)이고, 쓰는 명령은 그 DB 이름이 `lm_eval_` 로 시작할 때만 돈다
(격리 개발 DB·테스트 DB 를 지키려고). 운영 DB 는 앱의 로컬 DB 규칙으로 거부한다."""

import contextlib
import uuid
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from api.chat.prompt_builder import PromptNames, load_active_prompt_set
from api.chat.turn_prompt import JudgmentPromptSets, generation_prompt_set, judgment_prompt_sets
from api.core.config import settings
from api.db.models import ChatRoom
from api.db.models.character import CharacterVersionDetail
from api.db.models.persona import UserPersona
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import StartingSetup
from api.llm.chat_models import ChatModelId, PromptSetModelId
from replay.local_db import ensure_local_database

from memory_eval.arm_env import BARE_SUFFIX, BUNDLE1_ARMS, BUNDLE1_SWITCHES, POST_HISTORY_SWITCHES
from memory_eval.checkpoint import database_name, ensure_eval_db_name

# 갈래 = 같은 DB 상태에서 조립만 달리하는 설정 묶음. 회상 스위치는 회상을 구현한 코드에만 있다. A2·B2 는 2차 런의 두 갈래
# (둘 다 회상을 켜고 B2 만 사실 섹션을 싣는다 — 서버 env 전체는 `memory_eval.arm_env` 모듈) — 사실 주입 설정이 없는 코드면
# 거부된다.
ARMS: dict[str, dict[str, Any]] = {
    "baseline": {},
    "A": {"memory_episodes_recall": False},
    "B": {"memory_episodes_recall": True},
    "A2": {"memory_episodes_recall": True, "memory_facts_inject": False},
    "B2": {"memory_episodes_recall": True, "memory_facts_inject": True},
}
# 묶음 1 의 여섯 갈래 — 설정 칸 이름은 env 표(`memory_eval.arm_env`)의 스위치 이름을 소문자로 한 것이다. 요약 표기·지식 범위
# 필터·임베딩 읽기 설정이 없는 코드면 여섯 갈래 모두 거부된다(모두 같은 이미지에서 돌아야 갈래 사이 차이가 스위치뿐이다).
ARMS.update(
    {
        arm: {name.lower(): on for name, on in zip(BUNDLE1_SWITCHES, switches, strict=True)}
        for arm, switches in BUNDLE1_ARMS.items()
    }
)
# B 계열 갈래의 자기 재렌더 — 요약 표기·지식 범위 필터는 그대로, 대화 기록 뒤 섹션만 끈다.
ARMS.update(
    {
        f"{arm}{BARE_SUFFIX}": {**ARMS[arm], **dict.fromkeys(POST_HISTORY_SWITCHES, False)}
        for arm in BUNDLE1_ARMS
        if ARMS[arm]["memory_summary_secret_marking"]
    }
)


def work_database_url(*, writes: bool) -> str:
    url = settings.database_url
    ensure_local_database(url, tool="memory_eval")
    if writes:
        ensure_eval_db_name(database_name(url))
    return url


def make_engine(url: str) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(url)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


# 하네스가 싣는 채팅 레인.
Lane = Literal["story", "character"]


@dataclass(frozen=True)
class RoomContext:
    room: ChatRoom
    # 캐릭터 방은 시작설정이 없다(None).
    setup: StartingSetup | None
    names: PromptNames
    lane: Lane


async def load_room(db: AsyncSession, room_id: uuid.UUID, *, lane: Lane | None = None) -> RoomContext:
    """방과 그 레인. `lane` 을 주면 방의 레인과 같아야 한다(다른 레인의 대본·세트로 돌리지 않게)."""
    room = await db.get(ChatRoom, room_id)
    if room is None:
        raise SystemExit(f"방이 없다: {room_id}")
    room_lane: Lane = "character" if room.starting_setup_entity_id is None else "story"
    if lane is not None and lane != room_lane:
        raise SystemExit(f"방 {room_id} 의 레인은 {room_lane} 인데 {lane} 레인으로 돌리려 했다")
    setup = None
    if room_lane == "story":
        setup = await db.scalar(
            select(StartingSetup).where(
                StartingSetup.content_version_id == room.content_version_id,
                StartingSetup.entity_id == room.starting_setup_entity_id,
            )
        )
        if setup is None:
            raise SystemExit("방이 고정한 버전에 시작설정 행이 없다")
    persona = await db.get(UserPersona, room.persona_id) if room.persona_id is not None else None
    # 서버 턴과 같은 이름 — 캐릭터 방은 작품(캐릭터) 이름을 함께 준다. 접기는 이 이름으로 `{{char}}` 를 바꾸고 비밀 표기 슬롯의
    # 인물 목록 첫머리에 싣는다.
    char_name = None
    if room_lane == "character":
        detail = await db.get(CharacterVersionDetail, room.content_version_id)
        if detail is None:
            raise SystemExit("방이 고정한 버전에 캐릭터 상세 행이 없다")
        char_name = detail.name
    names = PromptNames(persona_name=persona.name if persona is not None else None, char_name=char_name)
    return RoomContext(room=room, setup=setup, names=names, lane=room_lane)


async def judgment_sets(db: AsyncSession, *, lane: Lane) -> JudgmentPromptSets:
    """그 레인의 판정·요약·추출 세트(앱의 `judgment_prompt_sets` 와 같은 고르기)."""
    gemini = await load_active_prompt_set(db, lane=lane, model="gemini")

    async def load(model: PromptSetModelId) -> tuple[PromptSet, list[PromptSection]]:
        return await load_active_prompt_set(db, lane=lane, model=model)

    return await judgment_prompt_sets(lane=lane, gemini_set=gemini, load=load)


async def generation_set(db: AsyncSession, model: ChatModelId, *, lane: Lane) -> tuple[PromptSet, list[PromptSection]]:
    gemini = await load_active_prompt_set(db, lane=lane, model="gemini")
    return await generation_prompt_set(db, lane=lane, model=model, gemini_set=gemini)


@contextlib.contextmanager
def arm_settings(arm: str) -> Iterator[None]:
    """갈래의 설정을 이 프로세스의 `settings` 에 잠시 씌운다. 그 설정 칸이 없는 코드면 거부한다."""
    overrides = ARMS[arm]
    missing = [name for name in overrides if not hasattr(settings, name)]
    if missing:
        raise SystemExit(f"갈래 {arm} 의 설정 {missing} 가 이 코드에 없다(회상을 구현한 코드에서만 돈다)")
    saved = {name: getattr(settings, name) for name in overrides}
    try:
        for name, value in overrides.items():
            setattr(settings, name, value)
        yield
    finally:
        for name, value in saved.items():
            setattr(settings, name, value)


def require_arm_supported(arm: str) -> None:
    """서버는 모르는 환경변수를 조용히 버린다 — 갈래 설정 칸이 없는 코드로 B 갈래를 돌리면 회상 없이 돈다. 같은 코드의
    이 프로세스에서 먼저 막는다."""
    missing = [name for name in ARMS[arm] if not hasattr(settings, name)]
    if missing:
        raise SystemExit(f"갈래 {arm} 의 설정 {missing} 가 이 코드에 없다(회상을 구현한 코드에서만 돈다)")


def arm_env(arm: str) -> dict[str, str]:
    """서버 프로세스용 같은 갈래 설정(환경변수)."""
    return {
        name.upper(): ("true" if value is True else "false" if value is False else str(value))
        for name, value in ARMS[arm].items()
    }


@contextlib.asynccontextmanager
async def app_client(cookie_value: str) -> AsyncIterator[httpx.AsyncClient]:
    """앱을 이 프로세스 안에서 ASGI 로 부르는 클라이언트(세션 쿠키는 드라이버가 저장한 값). 나올 때 앱의 DB 풀을 닫는다 —
    템플릿 복제가 작업 DB 에 남은 연결을 거부하므로. 앱 안의 모듈 싱글턴(Redis 클라이언트 등)은 처음 쓴 이벤트 루프에 묶이므로
    이 클라이언트는 한 프로세스에서 한 루프(넣기 한 번의 `asyncio.run`) 안에서만 쓴다 — `asyncio.run` 을 되풀이하는 프로브
    경로에서는 쓰지 않는다."""
    from api.db.session import engine as app_engine
    from api.main import app

    value = cookie_value.strip()
    if not value:
        raise SystemExit("세션 쿠키 값이 비었다")
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://memory-eval")
    client.cookies.set(settings.session_cookie_name, value)
    try:
        yield client
    finally:
        await client.aclose()
        await app_engine.dispose()


def describe(mapping: Mapping[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in mapping.items())
