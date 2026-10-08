"""마이그레이션이 심은 프롬프트 세트 검증.

`_migrated_schema`(세션 스코프 autouse, `conftest.py`)가 `alembic upgrade head`로 시드를
이미 넣어 두므로, 여기서는 그 결과를 `db_session`으로 읽기만 한다. 읽는 대상은 **head 상태의
활성 세트**(`load_active_prompt_set`, 프로덕션이 고르는 규칙과 같다)다 — 초기 시드
(`a69cbd40dec8`)가 아니다. 마이그레이션 `b72c33c70240`·`c328445d4c2d`·`2519dde454e0`이 행을 더한 새
published 세트를 만들어 레인마다 published가 여럿이다.

세 갈래:
1. head 활성 세트의 (channel, scope, slot, variant) 집합이 아래 표와 정확히 일치
   (누락·잉여 0).
2. `system` 채널 시드를 scope로 거르고 order로 정렬해 "\\n\\n"으로 이은 결과가
   `system_instruction_for()`의 실제 출력과 바이트 단위로 같다 — 6가지 경우 전부.
3. `UNIQUE(lane, model) WHERE status='draft'` / `UNIQUE(lane, model, version) WHERE status='published'`
   부분 인덱스가 실제로 **(레인, 모델) 축으로** 동작한다 —
   같은 (레인, 모델) 두 번째 draft/같은 (레인, 모델, 버전)의 두 번째 published가 IntegrityError로
   거부되고, 레인이나 모델이 다르면 **막지 않는다**(`alembic check`가 부분 인덱스의 predicate를
   비교하지 않는 사각지대라 행위 테스트가 유일한 검증 — 근거는 아래 테스트 함수
   docstring의 실측 기록).
4. 활성 세트 조회가 모델로 거른다 — 모델을 주지 않으면 Gemini 세트다.

1·2는 Gemini 세트를 본다. Claude 세트(system·generation 사본)는 `test_prompt_model_sets_migration.py`가 본다.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import PromptLane, load_active_prompt_set, system_instruction_for
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import StoryPromptTemplate

# 레인 분리 이후 (channel, scope, slot, variant) 전수는 레인별로 갈린다(story 62 / character 38 /
# publish_filter 4 — 마이그레이션 `a69cbd40dec8`의 `NEW_SECTION_IDS`·`_lanes_for` 배정
# 26/13/16에 마이그레이션 `b72c33c70240`이 story·character generation에 `user_persona`를 한 행씩 더했고,
# `c328445d4c2d`가 채팅방 기억 행을 더했다 — generation 2 · story ending_judgment 1 · 새 channel
# `memory_summary` 3. `2519dde454e0`이 story 레인에 미디어 북 칸 판정 channel `image_judgment` 3행을 더했고,
# `bd29dd69bc0f`가 publish_filter 레인에 미디어 북 칸 줄 슬롯 `media_book` 1행을 더했고, `859b0fb86629`가
# publish_filter 레인을 이미지 전용으로 바꿔 작가 글 슬롯 13개를 빼고 이미지 목록 슬롯 `image_list` 1행을 더했다.
# `2417f5829bb1`이 story generation 에 상황 노트 행 1개를 더해 story 37 이 됐고, `8e895c898730`이 사용자 이름 한 줄
# `user_name`을 story 5행·character 3행 더해 story 42 / character 22 가 됐고, `3bb2cc159b6d`가 소설화 세 채널
# (장 경계 제안 4·장 생성 6·문단 수정 6)을 두 레인에 16행씩 더해 story 58 / character 38 이다). 그 16행은 지금 채팅
# 레인에 얼려 둔 옛 문안이고, 소설 프롬프트 레인 리비전이 `novel` 레인에 경계 제안 4·화 생성 9·문단 수정 6 의 19행을
# 심었다(화 생성에 인물 메모·지난 화 요약·화 수 지시 슬롯이 늘었다). `d9768bc0cfee`가 story 레인에 스탯 규칙 판정
# 채널 `stat_rule_judgment` 4행을 더해 story 62 다.
# system/generation 채널의 `scope='both'` 행은 story·character 두 레인에 사본으로 들어간다.
_NOVELIZE_SLOTS: dict[str, set[tuple[str, str, str]]] = {
    "novelize_boundary": {
        ("both", "instruction", ""),
        ("both", "user_name", ""),
        ("both", "max_turns", ""),
        ("both", "turn_context", ""),
    },
    "novelize_chapter": {
        ("both", "instruction", ""),
        ("both", "work_setting", ""),
        ("both", "user_name", ""),
        ("both", "setting_notes", ""),
        ("both", "previous_excerpt", ""),
        ("both", "turn_context", ""),
    },
    "novelize_revise": {
        ("both", "instruction", ""),
        ("both", "work_setting", ""),
        ("both", "setting_notes", ""),
        ("both", "paragraphs", ""),
        ("both", "target_range", ""),
        ("both", "user_request", ""),
    },
}
_EXPECTED_SLOTS_BY_LANE: dict[PromptLane, dict[str, set[tuple[str, str, str]]]] = {
    "story": {
        "system": {
            ("story", "self_definition", ""),
            ("both", "rule_response_format", ""),
            ("both", "rule_user_agency", ""),
            ("both", "rule_open_turn", ""),
            ("both", "rule_rating", ""),
            ("story", "template_instruction", "basic"),
            ("story", "template_instruction", "emotional"),
            ("story", "template_instruction", "simulation"),
            ("story", "template_instruction", "custom"),
            ("both", "priority_tail", ""),
        },
        "generation": {
            ("story", "base_content", ""),
            ("story", "base_content", "custom"),
            ("story", "rules", ""),
            ("story", "user_goal", ""),
            ("story", "development_examples", ""),
            ("story", "prologue", ""),
            ("both", "user_persona", ""),
            ("both", "user_name", ""),
            ("both", "memory_note", ""),
            ("both", "memory_summary", ""),
            ("both", "history", ""),
            ("story", "keyword_notes", ""),
            ("story", "situation_notes", ""),
            ("story", "shortcut_prompt", ""),
            ("both", "final_frame", ""),
        },
        "stat_judgment": {
            ("story", "stat_defs_intro", ""),
            ("story", "user_name", ""),
            ("story", "turn_context", ""),
            ("story", "judgment_instruction", ""),
        },
        "stat_rule_judgment": {
            ("story", "stat_defs_intro", ""),
            ("story", "user_name", ""),
            ("story", "turn_context", ""),
            ("story", "judgment_instruction", ""),
        },
        "ending_judgment": {
            ("story", "user_name", ""),
            ("story", "memory_summary", ""),
            ("story", "history_header", ""),
            ("story", "turn_context", ""),
            ("story", "criteria", ""),
        },
        "memory_summary": {
            ("both", "instruction", ""),
            ("both", "user_name", ""),
            ("both", "previous_summary", ""),
            ("both", "turn_context", ""),
        },
        "image_judgment": {
            ("story", "image_list_intro", ""),
            ("story", "user_name", ""),
            ("story", "turn_context", ""),
            ("story", "judgment_instruction", ""),
        },
        **_NOVELIZE_SLOTS,
    },
    "character": {
        "system": {
            ("character", "self_definition", ""),
            ("both", "rule_response_format", ""),
            ("both", "rule_user_agency", ""),
            ("both", "rule_open_turn", ""),
            ("both", "rule_rating", ""),
            ("both", "priority_tail", ""),
        },
        "generation": {
            ("character", "character_prompt", ""),
            ("character", "example_dialogues", ""),
            ("both", "user_persona", ""),
            ("both", "user_name", ""),
            ("both", "memory_note", ""),
            ("both", "memory_summary", ""),
            ("both", "history", ""),
            ("both", "final_frame", ""),
        },
        "image_judgment": {
            ("character", "image_list_intro", ""),
            ("character", "user_name", ""),
            ("character", "turn_context", ""),
            ("character", "judgment_instruction", ""),
        },
        "memory_summary": {
            ("both", "instruction", ""),
            ("both", "user_name", ""),
            ("both", "previous_summary", ""),
            ("both", "turn_context", ""),
        },
        **_NOVELIZE_SLOTS,
    },
    "publish_filter": {
        "publish_filter": {
            ("character", "intro_instruction", ""),
            ("story", "intro_instruction", ""),
            ("both", "image_list", ""),
            ("both", "verdict_instruction", ""),
        },
    },
    "novel": {
        **_NOVELIZE_SLOTS,
        "novelize_chapter": _NOVELIZE_SLOTS["novelize_chapter"]
        | {("both", "character_notes", ""), ("both", "previous_summaries", ""), ("both", "episode_plan", "")},
    },
}


async def _active_sections(db_session: AsyncSession, *, lane: PromptLane) -> list[PromptSection]:
    _prompt_set, sections = await load_active_prompt_set(db_session, lane=lane)
    return sections


async def test_seeded_slot_set_matches_spec_exactly(db_session: AsyncSession) -> None:
    for lane, expected_slots in _EXPECTED_SLOTS_BY_LANE.items():
        sections = await _active_sections(db_session, lane=lane)

        actual: dict[str, set[tuple[str, str, str]]] = {}
        for section in sections:
            actual.setdefault(section.channel, set()).add((section.scope, section.slot, section.variant))

        assert actual == expected_slots, lane

        expected_total = sum(len(slots) for slots in expected_slots.values())
        assert len(sections) == expected_total, lane


def _reconstruct_system_instruction(
    sections: list[PromptSection], *, is_story_chat: bool, template: StoryPromptTemplate | None
) -> str:
    """렌더링 규약 — scope로 거르고 order로 정렬해 "\\n\\n"으로
    잇는다. `template_instruction` 슬롯은 `template`이 주어졌을 때만, 그 variant만 포함한다."""
    scope = "story" if is_story_chat else "character"
    picked = []
    for section in sections:
        if section.channel != "system":
            continue
        if section.scope not in (scope, "both"):
            continue
        if section.slot == "template_instruction":
            if template is None or section.variant != template.value:
                continue
        picked.append(section)
    picked.sort(key=lambda s: s.order)
    return "\n\n".join(section.body for section in picked)


@pytest.mark.parametrize(
    ("lane", "is_story_chat", "template"),
    [
        ("character", False, None),
        ("story", True, StoryPromptTemplate.BASIC),
        ("story", True, StoryPromptTemplate.EMOTIONAL),
        ("story", True, StoryPromptTemplate.SIMULATION),
        ("story", True, StoryPromptTemplate.CUSTOM),
        ("story", True, None),
    ],
    ids=[
        "character",
        "story_basic",
        "story_emotional",
        "story_simulation",
        "story_custom",
        "story_no_template",
    ],
)
async def test_system_channel_reconstruction_matches_current_code(
    db_session: AsyncSession, lane: PromptLane, is_story_chat: bool, template: StoryPromptTemplate | None
) -> None:
    sections = await _active_sections(db_session, lane=lane)
    reconstructed = _reconstruct_system_instruction(
        sections, is_story_chat=is_story_chat, template=template
    )
    expected = system_instruction_for(sections, is_story_chat=is_story_chat, template=template)
    assert reconstructed == expected


def _draft_prompt_set(*, lane: str, model: str = "gemini") -> PromptSet:
    return PromptSet(
        id=uuid.uuid4(),
        version=None,
        status="draft",
        lane=lane,
        model=model,
        user_label="사용자",
        story_assistant_label="진행자",
        story_example_label="서술자",
        character_assistant_label="캐릭터",
    )


def _published_prompt_set(*, lane: str, version: str, model: str = "gemini") -> PromptSet:
    return PromptSet(
        id=uuid.uuid4(),
        version=version,
        status="published",
        lane=lane,
        model=model,
        user_label="사용자",
        story_assistant_label="진행자",
        story_example_label="서술자",
        character_assistant_label="캐릭터",
        published_at=datetime.now(UTC),
    )


async def test_draft_partial_unique_index_rejects_second_draft(db_session: AsyncSession) -> None:
    """`UNIQUE(lane, model) WHERE status='draft'`가 실제로 **같은 (레인, 모델) 안에서** 초안 1개를
    강제하는지 — 같은 (레인, 모델)에 두 번째 draft를 넣으면 거부된다. `alembic check`는 부분
    인덱스의 술어를 비교하지 않으므로 행위 테스트가 유일한 검증이다."""
    db_session.add(_draft_prompt_set(lane="story"))
    await db_session.flush()

    db_session.add(_draft_prompt_set(lane="story"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_draft_partial_unique_index_allows_one_draft_per_lane(db_session: AsyncSession) -> None:
    """짝 — 인덱스가 실제로 `lane`을 유니크 축으로 삼는지: 세 레인 각각 초안 1행씩(3행)을
    함께 INSERT해도 전부 성공해야 한다. 이 짝이 없으면 위 "막는 쪽"만으로는 인덱스가
    여전히 예전처럼 `UNIQUE(status) WHERE status='draft'`(레인 무시, 전역 1개)로 남아
    있어도 그대로 통과한다 — 위 테스트는 같은 레인 두 초안이라 두 형태가 같은 값을
    내기 때문이다. 인덱스가 `lane`을 축으로 넓어지지 않았다면(예: 여전히 컬럼이 없거나
    다른 컬럼이라면) 이 3행 중 두 번째부터 IntegrityError가 나 이 테스트가 실패했을
    것이다."""
    for lane in ("story", "character", "publish_filter"):
        db_session.add(_draft_prompt_set(lane=lane))
    await db_session.flush()


async def test_published_version_partial_unique_index_rejects_duplicate_version(
    db_session: AsyncSession,
) -> None:
    """`UNIQUE(lane, model, version) WHERE status='published'`가 실제로 **같은 (레인, 모델) 안에서**
    버전 중복을 막는지 — `ix_prompt_sets_draft`와 정확히 같은 이유로(부분 인덱스
    predicate는 `alembic check`가 비교하지 않는다) 행위 테스트가 유일한 검증이다. dev
    Postgres에서 이 인덱스를 잠시 지운 뒤 같은 시나리오를 재현하면 두 번째 INSERT가
    에러 없이 성공한다 — 이 인덱스가 없으면 이 테스트가 실패한다는 것을 그렇게 직접
    확인했다."""
    db_session.add(_published_prompt_set(lane="story", version="9001"))
    await db_session.flush()

    db_session.add(_published_prompt_set(lane="story", version="9001"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_published_version_partial_unique_index_allows_different_versions(
    db_session: AsyncSession,
) -> None:
    """짝 — 같은 버전 문자열이라도 **레인이 다르면** 인덱스가 과하게 막지 않는다. 이게
    바로 이 인덱스의 목적이다 — "버전이 전역에
    유일"에서 "레인별로 유일"로 좁히는 것. 이 짝이 없으면 위 "막는 쪽"만으로는 인덱스가
    여전히 예전처럼 `UNIQUE(version) WHERE status='published'`(레인 무시, 전역
    유니크)로 남아 있어도 그대로 통과한다 — 위 테스트는 같은 레인 같은 버전이라 두
    형태가 같은 값을 내기 때문이다. 인덱스가 `lane`을 포함하지 않았다면 아래 두 번째
    INSERT도 IntegrityError로 거부돼 이 테스트가 실패했을 것이다."""
    db_session.add(_published_prompt_set(lane="story", version="9001"))
    db_session.add(_published_prompt_set(lane="character", version="9001"))
    await db_session.flush()


async def test_draft_partial_unique_index_allows_one_draft_per_model_in_a_lane(db_session: AsyncSession) -> None:
    """짝 — 인덱스가 `model`도 유니크 축으로 삼는지: 같은 레인이라도 모델마다 초안 1행씩은 함께 들어간다. 인덱스가
    `(lane)`만 보던 예전 형태로 남아 있으면 두 번째 INSERT가 IntegrityError로 이 테스트가 실패한다(위 거부 테스트는
    같은 모델 두 초안이라 두 형태가 같은 값을 낸다)."""
    for model in ("gemini", "sonnet", "opus"):
        db_session.add(_draft_prompt_set(lane="story", model=model))
    await db_session.flush()


async def test_published_version_partial_unique_index_allows_the_same_version_across_models(
    db_session: AsyncSession,
) -> None:
    """짝 — 같은 레인·같은 버전이라도 모델이 다르면 막지 않는다. 인덱스가 `(lane, version)`으로 남아 있으면 두 번째
    INSERT가 거부돼 이 테스트가 실패한다."""
    db_session.add(_published_prompt_set(lane="story", version="9001", model="gemini"))
    db_session.add(_published_prompt_set(lane="story", version="9001", model="sonnet"))
    await db_session.flush()


async def test_published_version_partial_unique_index_rejects_duplicate_version_within_a_claude_chain(
    db_session: AsyncSession,
) -> None:
    db_session.add(_published_prompt_set(lane="character", version="9001", model="opus"))
    await db_session.flush()

    db_session.add(_published_prompt_set(lane="character", version="9001", model="opus"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_load_active_prompt_set_filters_by_model(db_session: AsyncSession) -> None:
    """같은 레인에 더 최신 published_at 의 Claude 게시본이 있어도 모델을 주지 않으면 Gemini 세트다(판정·요약이 읽는
    세트가 Claude 게시에 휩쓸리지 않는다). 모델을 주면 그 체인의 최신 게시본이다."""
    gemini_set, _ = await load_active_prompt_set(db_session, lane="story")
    assert gemini_set.published_at is not None
    newer_sonnet = _published_prompt_set(lane="story", version="9002", model="sonnet")
    newer_sonnet.published_at = gemini_set.published_at + timedelta(hours=1)
    db_session.add(newer_sonnet)
    await db_session.flush()

    assert (await load_active_prompt_set(db_session, lane="story"))[0].id == gemini_set.id
    assert (await load_active_prompt_set(db_session, lane="story", model="gemini"))[0].id == gemini_set.id
    assert (await load_active_prompt_set(db_session, lane="story", model="sonnet"))[0].id == newer_sonnet.id
