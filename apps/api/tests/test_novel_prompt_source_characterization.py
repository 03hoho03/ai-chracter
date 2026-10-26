"""소설 프롬프트 빌더 일곱 개의 렌더 결과 기대값 — 라벨·등급 규칙을 어디서 읽든 같은 글이 나가야 한다.

기대값 파일(`fixtures/novel_prompt_source_characterization.json`)은 라벨·등급 규칙을 소설 원작 종류의 채팅 Gemini 활성 세트에서
읽던 코드로 만든다. 케이스는 빌더 7 × 원작 2(스토리·캐릭터) × 소설 체인 3(gemini·sonnet·opus) = 42 이고, 케이스마다 지시문과
본문의 sha256 만 적는다(문안 원문은 적지 않는다). 렌더 입력은 이 파일의 `_INPUTS` 가 유일한 정의처다.

그때 코드에서 경계 제안·문단 수정·여러 문단 수정·묶음 재검사는 고른 모델과 무관하게 늘 소설 Gemini 체인 세트로 렌더했으므로,
sonnet·opus 체인의 그 네 빌더 기대값은 Gemini 체인 렌더다.

기대값은 라벨·등급 규칙을 소설 레인으로 옮기기 전 커밋에서 `NOVEL_PROMPT_SOURCE_GOLDEN_WRITE=1` 로 그 커밋의 이 파일을 돌려
기록했다. 다시 만들려면 그 커밋으로 돌아가 같은 스위치로 돌린다 — 지금 코드로 만들면 대조가 항진명제가 되므로, 기대값이 다르면
파일을 고치지 말고 멈춘다.

이 파일은 같은 렌더를 지금 경로(라벨은 소설 Gemini 체인 세트, 등급 규칙은 그 체인 세트의 `novelize_rating` 채널)로 다시 해 같은
sha 가 나오는지 보고, 채팅 세트 값이 렌더에 섞이지 않는지(대조군), 소설 세트 값이 실제 입력인지(역방향)도 본다.
"""

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import load_active_prompt_set
from api.db.models.prompt import PromptSection, PromptSet
from api.novelize.inputs import load_novel_prompt_source
from api.novelize.prompts import (
    NovelizePrompt,
    build_novelize_boundary_prompt,
    build_novelize_chapter_prompt,
    build_novelize_episode_outline_prompt,
    build_novelize_outline_prompt,
    build_novelize_revise_blocks_prompt,
    build_novelize_revise_prompt,
    build_novelize_revise_recheck_prompt,
)

FIXTURE = Path(__file__).parent / "fixtures" / "novel_prompt_source_characterization.json"

SCOPES: tuple[str, ...] = ("story", "character")
MODELS: tuple[str, ...] = ("gemini", "sonnet", "opus")
BUILDERS: tuple[str, ...] = (
    "boundary",
    "chapter",
    "outline",
    "episode_outline",
    "revise",
    "revise_blocks",
    "revise_recheck",
)
# 그때 코드에서 고른 모델의 체인 세트로 렌더한 빌더 — 나머지는 늘 Gemini 체인이었다.
CHAIN_BUILDERS: frozenset[str] = frozenset({"chapter", "outline", "episode_outline"})

_TURN_LINES = "[턴 1] {assistant}: 비가 오네.\n[턴 2] {user}: 우산 같이 쓸래?\n[턴 2] {assistant}: 고마워."
_INPUTS: dict[str, dict[str, Any]] = {
    "boundary": {"max_turns": 2, "user_name": "하늘"},
    "chapter": {
        "work_setting": "작은 바닷가 마을의 하숙집 이야기.",
        "user_name": "하늘",
        "setting_notes": "하늘은 우산을 늘 두 개 들고 다닌다.",
        "previous_excerpt": "문이 닫히고 빗소리만 남았다.",
        "character_notes": "세빈: 말수가 적다.",
        "previous_summaries": "1화: 두 사람이 정류장에서 처음 만났다.",
        "episode_count": 2,
        "episode_chars": 3000,
        "novel_title_rule": "이번에는 소설 제목도 쓴다.",
        "scene_plan": "1. 정류장에서 다시 만난다.",
        "context_lines": "[턴 1] {assistant}: 지난번 일은 잊어.",
    },
    "outline": {
        "work_setting": "작은 바닷가 마을의 하숙집 이야기.",
        "user_name": "하늘",
        "setting_notes": "하늘은 우산을 늘 두 개 들고 다닌다.",
        "max_episodes": 4,
        "episode_hint": 2,
        "character_notes": "세빈: 말수가 적다.",
        "previous_summaries": "1화: 두 사람이 정류장에서 처음 만났다.",
        "context_lines": "[턴 1] {assistant}: 지난번 일은 잊어.",
    },
    "episode_outline": {
        "work_setting": "작은 바닷가 마을의 하숙집 이야기.",
        "user_name": "하늘",
        "setting_notes": "하늘은 우산을 늘 두 개 들고 다닌다.",
        "episode_outline": "2화 정류장: 두 사람이 비 오는 정류장에서 다시 만난다.",
        "character_notes": "세빈: 말수가 적다.",
        "previous_summaries": "1화: 두 사람이 정류장에서 처음 만났다.",
        "context_lines": "[턴 1] {assistant}: 지난번 일은 잊어.",
    },
    "revise": {
        "work_setting": "작은 바닷가 마을의 하숙집 이야기.",
        "setting_notes": "하늘은 우산을 늘 두 개 들고 다닌다.",
        "paragraphs": ["비가 왔다.", "세빈이 우산을 폈다.", "둘은 말없이 걸었다."],
        "first_index": 1,
        "last_index": 1,
        "user_request": "더 쓸쓸하게",
    },
    "revise_blocks": {
        "work_setting": "작은 바닷가 마을의 하숙집 이야기.",
        "setting_notes": "하늘은 우산을 늘 두 개 들고 다닌다.",
        "paragraph_lines": "[1] 비가 왔다.\n\n[2] 세빈이 우산을 폈다.\n\n[3] 둘은 말없이 걸었다.",
        "target_labels": [1, 3],
        "user_request": "더 쓸쓸하게",
    },
    "revise_recheck": {
        "edited_lines": "[2] 세빈이 낡은 우산을 폈다.",
        "patch_lines": "[3] 둘은 낡은 우산 아래에서 말없이 걸었다.",
        "paragraph_lines": "[1] 비가 왔다.",
    },
}


def case_key(builder: str, scope: str, model: str) -> str:
    return f"{builder}/{scope}/{model}"


def all_cases() -> list[tuple[str, str, str]]:
    return [(builder, scope, model) for builder in BUILDERS for scope in SCOPES for model in MODELS]


def _turn_lines(text: str, *, user: str, assistant: str) -> str:
    return text.format(user=user, assistant=assistant)


def digest(prompt: NovelizePrompt) -> dict[str, str]:
    return {
        "system": hashlib.sha256(prompt.system_instruction.encode()).hexdigest(),
        "prompt": hashlib.sha256(prompt.prompt.encode()).hexdigest(),
    }


def _render_with(
    builder: str, *, is_story: bool, sections: list[PromptSection], label_set: PromptSet
) -> NovelizePrompt:
    values = dict(_INPUTS[builder])
    user_label, assistant_label = labels_of(label_set, is_story=is_story)
    lines = _turn_lines(_TURN_LINES, user=user_label, assistant=assistant_label)
    if "context_lines" in values:
        values["context_lines"] = _turn_lines(values["context_lines"], user=user_label, assistant=assistant_label)
    common: dict[str, Any] = {"sections": sections, "is_story_chat": is_story}
    if builder == "boundary":
        return build_novelize_boundary_prompt(**common, label_set=label_set, turn_lines=lines, **values)
    if builder == "chapter":
        return build_novelize_chapter_prompt(**common, label_set=label_set, turn_lines=lines, **values)
    if builder == "outline":
        return build_novelize_outline_prompt(**common, label_set=label_set, turn_lines=lines, **values)
    if builder == "episode_outline":
        return build_novelize_episode_outline_prompt(**common, label_set=label_set, turn_lines=lines, **values)
    if builder == "revise":
        return build_novelize_revise_prompt(**common, **values)
    if builder == "revise_blocks":
        return build_novelize_revise_blocks_prompt(**common, **values)
    return build_novelize_revise_recheck_prompt(**common, **values)


def labels_of(prompt_set: PromptSet, *, is_story: bool) -> tuple[str, str]:
    return prompt_set.user_label, (
        prompt_set.story_assistant_label if is_story else prompt_set.character_assistant_label
    )


async def render_case(db: AsyncSession, builder: str, scope: str, model: str) -> NovelizePrompt:
    """지금 경로 — 문안·등급 규칙은 그 소설 체인 세트, 라벨은 소설 Gemini 체인 세트에서 읽는다."""
    db.expire_all()
    source = await load_novel_prompt_source(db, model=model)  # type: ignore[arg-type]
    return _render_with(builder, is_story=scope == "story", sections=source.sections, label_set=source.label_set)


def _text(prompt: NovelizePrompt) -> str:
    return f"{prompt.system_instruction}\n---\n{prompt.prompt}"


_CHAT_LABEL_MARK = "채팅표지라벨"
_CHAT_RATING_MARK = "채팅표지등급"
_NOVEL_LABEL_MARK = "소설표지라벨"
_NOVEL_RATING_MARK = "소설표지등급"
_RATING_BUILDERS = frozenset({"chapter", "outline", "episode_outline", "revise", "revise_blocks"})
_LABEL_BUILDERS = frozenset({"boundary", "chapter", "outline", "episode_outline"})


async def _mark_set(db: AsyncSession, set_id: uuid.UUID, *, label_mark: str, rating_mark: str, channel: str) -> None:
    """세트의 라벨 셋과 그 채널의 `rule_rating` 본문을 표지로 바꾼다(테스트 트랜잭션 안이라 롤백된다)."""
    await db.execute(
        sa.update(PromptSet)
        .where(PromptSet.id == set_id)
        .values(
            user_label=f"{label_mark}사용자",
            story_assistant_label=f"{label_mark}진행자",
            character_assistant_label=f"{label_mark}캐릭터",
        )
    )
    await db.execute(
        sa.update(PromptSection)
        .where(
            PromptSection.prompt_set_id == set_id,
            PromptSection.channel == channel,
            PromptSection.slot == "rule_rating",
        )
        .values(body=f"[수위]\n{rating_mark} 문장.")
    )
    await db.flush()
    db.expire_all()


def _expected() -> dict[str, dict[str, str]]:
    loaded: dict[str, dict[str, str]] = json.loads(FIXTURE.read_text())
    return loaded


async def test_every_case_renders_the_digest_recorded_with_the_old_source(db_session: AsyncSession) -> None:
    """42 케이스가 라벨·등급 규칙을 채팅 세트에서 빌리던 코드가 낸 글과 바이트까지 같다. 깨지는 시나리오: 소설 세트로 옮긴
    라벨·등급 규칙이 원본과 한 글자라도 달라(캐릭터 라벨을 스토리 세트에서 복사하는 등) 같은 입력이 다른 프롬프트를 낸다."""
    expected = _expected()
    assert len(expected) == 42
    actual = {
        case_key(builder, scope, model): digest(await render_case(db_session, builder, scope, model))
        for builder, scope, model in all_cases()
    }
    assert actual == expected


async def test_chat_set_labels_and_rating_never_reach_a_novel_prompt(db_session: AsyncSession) -> None:
    """채팅 두 Gemini 활성 세트의 라벨·등급 규칙을 표지로 바꿔도 42 케이스 렌더에 표지가 없고 sha 도 그대로다. 깨지는
    시나리오: 소설 호출이 여전히 채팅 세트에서 읽어, 운영자가 채팅 등급 규칙을 고치면 소설 글이 조용히 따라 바뀐다."""
    for lane in ("story", "character"):
        chat_set, _ = await load_active_prompt_set(db_session, lane=lane)
        await _mark_set(
            db_session, chat_set.id, label_mark=_CHAT_LABEL_MARK, rating_mark=_CHAT_RATING_MARK, channel="system"
        )
    expected = _expected()
    for builder, scope, model in all_cases():
        prompt = await render_case(db_session, builder, scope, model)
        text = _text(prompt)
        assert _CHAT_LABEL_MARK not in text and _CHAT_RATING_MARK not in text, (builder, scope, model)
        assert digest(prompt) == expected[case_key(builder, scope, model)], (builder, scope, model)


async def test_novel_set_rating_is_the_input_of_each_chain(db_session: AsyncSession) -> None:
    """역방향 — 각 소설 체인 세트의 `novelize_rating` 을 표지로 바꾸면 등급 규칙을 붙이는 다섯 빌더의 지시문에 표지가 나타나고
    sha 가 바뀐다. 붙이지 않는 두 빌더(경계·재검사)는 그대로다. 깨지는 시나리오: 렌더가 등급 규칙을 다른 곳에서 읽어 위 대조군이
    아무것도 증명하지 못한다."""
    expected = _expected()
    for model in MODELS:
        source = await load_novel_prompt_source(db_session, model=model)  # type: ignore[arg-type]
        await db_session.execute(
            sa.update(PromptSection)
            .where(
                PromptSection.prompt_set_id == source.prompt_set.id,
                PromptSection.channel == "novelize_rating",
                PromptSection.slot == "rule_rating",
            )
            .values(body=f"[수위]\n{_NOVEL_RATING_MARK} 문장.")
        )
    await db_session.flush()
    for builder, scope, model in all_cases():
        prompt = await render_case(db_session, builder, scope, model)
        changed = digest(prompt) != expected[case_key(builder, scope, model)]
        if builder in _RATING_BUILDERS:
            assert _NOVEL_RATING_MARK in prompt.system_instruction and changed, (builder, scope, model)
        else:
            assert _NOVEL_RATING_MARK not in _text(prompt) and not changed, (builder, scope, model)


async def test_novel_gemini_set_labels_are_the_label_source_of_every_chain(db_session: AsyncSession) -> None:
    """역방향 — (novel, gemini) 활성 세트의 라벨만 표지로 바꿔도 세 체인 모두의 라벨 쓰는 빌더 렌더에 표지가 나타나고 sha 가
    바뀐다. 라벨은 체인과 무관하게 소설 Gemini 체인 한 곳에서 읽는다. 깨지는 시나리오: Claude 체인이 자기 세트의 라벨 칸을 읽어,
    어드민이 숨겨 둔 그 칸 값이 원문 줄에 실린다."""
    gemini_set, _ = await load_active_prompt_set(db_session, lane="novel")
    await db_session.execute(
        sa.update(PromptSet)
        .where(PromptSet.id == gemini_set.id)
        .values(
            user_label=f"{_NOVEL_LABEL_MARK}사용자",
            story_assistant_label=f"{_NOVEL_LABEL_MARK}진행자",
            character_assistant_label=f"{_NOVEL_LABEL_MARK}캐릭터",
        )
    )
    await db_session.flush()
    expected = _expected()
    for builder, scope, model in all_cases():
        prompt = await render_case(db_session, builder, scope, model)
        changed = digest(prompt) != expected[case_key(builder, scope, model)]
        if builder in _LABEL_BUILDERS:
            assert _NOVEL_LABEL_MARK in prompt.prompt and changed, (builder, scope, model)
        else:
            assert _NOVEL_LABEL_MARK not in _text(prompt) and not changed, (builder, scope, model)
