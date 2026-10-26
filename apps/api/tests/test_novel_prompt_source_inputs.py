"""소설 호출의 입력 조립이 채팅 세트를 읽지 않는다 — 입력 단위 대조군과 그 읽기 자리를 고정하는 AST 가드.

렌더 단위 대조군(`test_novel_prompt_source_characterization.py`)은 빌더에 넘기는 세트를 테스트가 고른다. 여기서는 실제 호출 경로가
세트를 스스로 읽게 둔다 — 묶음 생성·다시 만들기 입력(`build_chapter_input`), 구성 흐름의 전체 구성안·장면 구성안·원고·원고 다시
만들기(라우트에서 작업 실행까지, 모델은 가짜 클라이언트), 경계 제안(`suggest_end_turn`). 채팅 두 Gemini 활성 세트의 라벨·등급 규칙을
표지 문자열로 바꾼 DB 에서 모델이 받은 지시문·본문에 표지가 한 번도 없고, 등급 규칙을 붙이는 호출은 소설 세트의 등급 규칙 본문을
지시문에 싣는다. 깨지는 시나리오: 입력 조립 어딘가가 여전히 원작 종류의 채팅 세트에서 라벨이나 등급 규칙을 읽어, 운영자가 채팅
문안을 고치면 소설 글이 조용히 따라 바뀐다."""

import ast
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat.prompt_builder import load_active_prompt_set
from api.core.config import settings
from api.db.models import ChatMessage, NovelJob
from api.db.models.novel import Novel, NovelBatch, NovelChapter
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.client import LLMCallContext, LLMClient, T
from api.novelize import inputs, runner
from api.novelize import router as novelize_router
from api.novelize.boundary import suggest_end_turn
from api.novelize.inputs import load_novel_prompt_source
from api.novelize.source import group_turns, load_segment, segment_hash
from factories import (
    _batch_output,
    _clear_llm_override,
    _novel_setup,
    _override_llm_client,
    _room_messages,
    _set_model_price,
)

_LABEL_MARK = "채팅표지라벨"
_RATING_MARK = "채팅표지등급"
_SECTIONS = (("include", 0, 4), ("context", 5, 6), ("include", 9, 12))
_TWO_EPISODES = [
    {"title": "첫 만남", "summary": "둘이 처음 만났다.", "goal": "서로를 궁금해한다.", "start_turn": 1, "end_turn": 2},
    {"title": "다시 만남", "summary": "둘이 다시 만났다.", "goal": "약속을 남긴다.", "start_turn": 3, "end_turn": 5},
]
_PARAGRAPH = "비가 그치지 않는 저녁이었다. 서진은 정류장 지붕 아래에서 오래 서 있었다. " * 4
_BODY = "\n\n".join(f"{n}번째 문단. {_PARAGRAPH}" for n in range(1, 7))
_NOVELIZE_DIR = Path(__file__).resolve().parents[1] / "src" / "api" / "novelize"


def _scene(title: str, start: int, end: int) -> dict[str, Any]:
    return {
        "title": title,
        "summary": f"{title} 장면에서 일이 일어났다.",
        "purpose": f"{title} 뒤에 무엇이 달라진다.",
        "characters": ["서진", "도윤"],
        "flashback": False,
        "start_turn": start,
        "end_turn": end,
    }


class _RecordingLLM(LLMClient):
    """소설 호출 넷(원고 스트림, 전체 구성안·장면 구성안·경계 제안 구조화)을 받아 (호출 위치, 본문, 지시문)을 적는다."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.calls.append((usage.call_site, prompt, system_instruction or ""))
        yield _batch_output(_BODY)

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:  # pragma: no cover - 불리면 시험 실패
        raise AssertionError("소설 호출은 지시문 없는 구조화 호출을 쓰지 않는다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        self.calls.append((usage.call_site, prompt, system_instruction))
        if usage.call_site == "novelize_outline":
            return response_schema.model_validate({"episodes": _TWO_EPISODES})
        if usage.call_site == "novelize_episode_outline":
            return response_schema.model_validate({"scenes": [_scene("시작", 1, 1), _scene("이어짐", 2, 2)]})
        if usage.call_site == "novelize_boundary":
            return response_schema.model_validate({"end_turn": 1, "reason": "장면이 매듭지어진다."})
        raise AssertionError(f"예상하지 않은 호출: {usage.call_site}")


@pytest.fixture(autouse=True)
def _prices(monkeypatch: pytest.MonkeyPatch) -> None:
    """잔액 100 안에서 구성안·장면 구성안·원고·원고 다시 만들기를 함께 사는 고정 단가."""
    _set_model_price(monkeypatch, "gemini", novel_outline=11)
    _set_model_price(monkeypatch, "gemini", novel_episode_outline=7)
    _set_model_price(monkeypatch, "gemini", novel_episode=20)


@pytest.fixture(autouse=True)
def llm() -> Iterator[_RecordingLLM]:
    fake = _RecordingLLM()
    _override_llm_client(fake)
    yield fake
    _clear_llm_override()


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    seen: list[uuid.UUID] = []

    async def record(_factory: Any, _llm: Any, job_id: uuid.UUID) -> None:
        seen.append(job_id)

    monkeypatch.setattr(novelize_router, "enqueue_job", record)
    return seen


def _factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")


async def _run(db_session: AsyncSession, llm: LLMClient, job_id: uuid.UUID) -> NovelJob:
    await runner.run_job(_factory(db_session), llm, job_id)
    return await db_session.get_one(NovelJob, job_id, populate_existing=True)


async def _mark_chat_sets(db: AsyncSession) -> None:
    """채팅 두 Gemini 활성 세트의 라벨 셋과 `system/rule_rating` 본문을 표지로 바꾼다(테스트 트랜잭션 안이라 롤백된다)."""
    for lane in ("story", "character"):
        chat_set, _ = await load_active_prompt_set(db, lane=lane)
        await db.execute(
            sa.update(PromptSet)
            .where(PromptSet.id == chat_set.id)
            .values(
                user_label=f"{_LABEL_MARK}사용자",
                story_assistant_label=f"{_LABEL_MARK}진행자",
                character_assistant_label=f"{_LABEL_MARK}캐릭터",
            )
        )
        await db.execute(
            sa.update(PromptSection)
            .where(
                PromptSection.prompt_set_id == chat_set.id,
                PromptSection.channel == "system",
                PromptSection.slot == "rule_rating",
            )
            .values(body=f"[수위]\n{_RATING_MARK} 문장.")
        )
    await db.commit()
    db.expire_all()


async def _novel_rating_body(db: AsyncSession, *, scope: str) -> str:
    _, sections = await load_active_prompt_set(db, lane="novel")
    (body,) = [s.body for s in sections if s.channel == "novelize_rating" and s.scope == scope]
    return body


def _assert_unmarked(text: str, where: str) -> None:
    assert _LABEL_MARK not in text and _RATING_MARK not in text, where


async def _select(
    db_client: httpx.AsyncClient, novel_id: uuid.UUID, ms: list[ChatMessage], sections: tuple[tuple[str, int, int], ...]
) -> None:
    base = f"/novels/{novel_id}/source-selection"
    state = (await db_client.get(base)).json()
    latest = state["draft"] or state["approved"]
    shown = latest or state["proposal"]
    saved = await db_client.put(
        f"{base}/draft",
        json={
            "baseRevision": None if latest is None else latest["revision"],
            "extendToRoomEnd": False,
            "roomEndMessageId": shown["roomEndMessageId"],
            "sections": [
                {"mode": mode, "startMessageId": str(ms[a].id), "endMessageId": str(ms[b].id)}
                for mode, a, b in sections
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    approved = await db_client.post(f"{base}/approve", json={"revision": saved.json()["draft"]["revision"]})
    assert approved.status_code == 200, approved.text


async def test_the_outline_flow_inputs_never_carry_the_chat_sets_labels_or_rating(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[uuid.UUID],
    llm: _RecordingLLM,
) -> None:
    """전체 구성안(`load_outline_source` 를 거치는 입력)·장면 구성안·원고·원고 다시 만들기가 모델에 보낸 글에 채팅 세트 표지가 없고,
    네 호출 모두 소설 세트의 등급 규칙을 지시문에 싣는다."""
    monkeypatch.setattr(settings, "novelize_outline_flow_enabled", True)
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=6)
    ms = await _room_messages(db_session, room.room_id)
    await _mark_chat_sets(db_session)
    rating = await _novel_rating_body(db_session, scope="character")
    await _select(db_client, novel_id, ms, _SECTIONS)

    outline = await db_client.post(f"/novels/{novel_id}/outline", json={"model": "gemini", "expectedCost": 11})
    assert outline.status_code == 202, outline.text
    assert (await _run(db_session, llm, enqueued[-1])).status == "succeeded"
    state = (await db_client.get(f"/novels/{novel_id}/outline")).json()
    approved = await db_client.post(f"/novels/{novel_id}/outline/approve", json={"revision": state["draft"]["revision"]})
    assert approved.status_code == 200, approved.text
    key = approved.json()["approved"]["episodes"][0]["key"]

    scenes_url = f"/novels/{novel_id}/outline/episodes/{key}/scenes"
    scenes = await db_client.post(scenes_url, json={"model": "gemini", "expectedCost": 7})
    assert scenes.status_code == 202, scenes.text
    assert (await _run(db_session, llm, enqueued[-1])).status == "succeeded"
    scene_state = (await db_client.get(scenes_url)).json()
    scene_ok = await db_client.post(f"{scenes_url}/approve", json={"revision": scene_state["draft"]["revision"]})
    assert scene_ok.status_code == 200, scene_ok.text

    chapter = await db_client.post(
        f"/novels/{novel_id}/outline/episodes/{key}/chapter", json={"model": "gemini", "expectedCost": 20}
    )
    assert chapter.status_code == 202, chapter.text
    written = await _run(db_session, llm, enqueued[-1])
    assert written.status == "succeeded", written.failure_code
    regenerate = await db_client.post(
        f"/novels/{novel_id}/outline/chapters/{written.chapter_id}/regenerate",
        json={"model": "gemini", "expectedCost": 20},
    )
    assert regenerate.status_code == 202, regenerate.text
    assert (await _run(db_session, llm, enqueued[-1])).status == "succeeded"

    assert [site for site, _, _ in llm.calls] == [
        "novelize_outline",
        "novelize_episode_outline",
        "novelize_chapter",
        "novelize_chapter",
    ]
    for site, prompt, system in llm.calls:
        _assert_unmarked(prompt + system, site)
        assert rating in system, site


async def test_the_old_flow_chapter_and_regenerate_inputs_never_carry_the_chat_sets_labels_or_rating(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """옛 흐름 묶음 생성과 다시 만들기 입력(`build_chapter_input`)에 채팅 세트 표지가 없고, 소설 세트 등급 규칙과 소설 Gemini 체인
    세트의 라벨이 실린다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=3)
    ms = await _room_messages(db_session, room.room_id)
    await _mark_chat_sets(db_session)
    novel = await db_session.get_one(Novel, novel_id, populate_existing=True)
    rating = await _novel_rating_body(db_session, scope="character")
    label_set = (await load_novel_prompt_source(db_session)).label_set
    start, end = ms[0], room.turns[2][1]
    segment: dict[str, Any] = {
        "start_message_id": start.id,
        "start_message_created_at": start.created_at,
        "end_message_id": end.id,
        "end_message_created_at": end.created_at,
    }

    generate = NovelJob(
        id=uuid.uuid4(), novel_id=novel.id, user_id=novel.user_id, kind="chapter_generate", episode_count_target=1, **segment
    )
    built = await inputs.build_chapter_input(db_session, generate, novel)

    messages = await load_segment(
        db_session, room.room_id, (start.created_at, start.id), (end.created_at, end.id)
    )
    stored: dict[str, Any] = {**segment, "assistant_message_count": len(group_turns(messages))}
    batch = NovelBatch(novel_id=novel.id, ordinal=1, target_episode_count=1, source_hash=segment_hash(messages), **stored)
    db_session.add(batch)
    await db_session.flush()
    db_session.add(
        NovelChapter(
            novel_id=novel.id, ordinal=1, batch_id=batch.id, episode_index=0, source_hash=batch.source_hash, **stored
        )
    )
    await db_session.flush()
    regenerate = NovelJob(
        id=uuid.uuid4(), novel_id=novel.id, user_id=novel.user_id, kind="chapter_regenerate", batch_id=batch.id, **segment
    )
    rebuilt = await inputs.build_chapter_input(db_session, regenerate, novel)

    for where, prompt in (("generate", built.prompt), ("regenerate", rebuilt.prompt)):
        _assert_unmarked(prompt.system_instruction + prompt.prompt, where)
        assert rating in prompt.system_instruction, where
        assert f"{label_set.user_label}: " in prompt.prompt, where


async def test_the_boundary_suggestion_never_carries_the_chat_sets_labels(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _RecordingLLM
) -> None:
    """경계 제안이 호출부와 같은 꼴로 소설 프롬프트 소스를 읽어 부르면 모델이 받은 글에 채팅 세트 표지가 없고, 원문 줄 라벨은 소설
    Gemini 체인 세트의 것이다(경계 제안은 등급 규칙을 붙이지 않는다)."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=3)
    ms = await _room_messages(db_session, room.room_id)
    await _mark_chat_sets(db_session)
    novel = await db_session.get_one(Novel, novel_id, populate_existing=True)
    source = await load_novel_prompt_source(db_session)
    end = room.turns[3][1]
    turns = group_turns(
        await load_segment(db_session, room.room_id, (ms[0].created_at, ms[0].id), (end.created_at, end.id))
    )

    suggested = await suggest_end_turn(
        llm, novel=novel, turns=turns, sections=source.sections, label_set=source.label_set, room_id=room.room_id
    )

    assert suggested == (1, "장면이 매듭지어진다.")
    ((site, prompt, system),) = llm.calls
    assert site == "novelize_boundary"
    _assert_unmarked(prompt + system, site)
    assert f"{source.label_set.user_label}: " in prompt


def _prompt_set_reads(source: str) -> list[tuple[int, str]]:
    """`load_active_prompt_set(...)` 호출마다 (줄, `lane=` 값의 소스 글자). `lane=` 이 없으면 빈 글자."""
    tree = ast.parse(source)
    reads: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        if name != "load_active_prompt_set":
            continue
        lane = next((kw.value for kw in node.keywords if kw.arg == "lane"), None)
        reads.append((node.lineno, "" if lane is None else ast.unparse(lane)))
    return reads


def test_novelize_reads_prompt_sets_only_from_the_novel_lane() -> None:
    """소설 호출 모듈은 프롬프트 세트를 `lane="novel"` 로만 읽는다. 원작 종류(`novel.content_type`)의 채팅 세트를 읽으면 라벨·등급
    규칙의 소스가 둘이 되어 소설 레인 문안을 고쳐도 반영되지 않거나 채팅 문안 수정이 소설 글을 바꾼다 — 위 대조군이 덮지 못한 새
    호출 자리도 여기서 막는다. 레인을 빼먹으면 기본값 없는 키워드라 타입 검사가 먼저 막지만, 같은 이유로 여기서도 거부한다."""
    offending = [
        f"{path.name}:{line} lane={lane or '(없음)'}"
        for path in sorted(_NOVELIZE_DIR.rglob("*.py"))
        for line, lane in _prompt_set_reads(path.read_text())
        if lane != "'novel'"
    ]
    assert offending == []


def test_the_ast_guard_sees_a_chat_lane_read() -> None:
    """가드 자체의 신호 — 원작 종류 레인으로 읽는 꼴을 실제로 잡는다(못 잡으면 위 가드가 늘 통과하는 항진명제다)."""
    sample = (
        "async def f(db, novel):\n"
        "    await load_active_prompt_set(db, lane=novel.content_type)\n"
        "    await load_active_prompt_set(db, lane=\"novel\", model=\"gemini\")\n"
    )
    assert _prompt_set_reads(sample) == [(2, "novel.content_type"), (3, "'novel'")]
