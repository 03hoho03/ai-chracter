"""마이그레이션이 심은 프롬프트 세트 검증.

`_migrated_schema`(세션 스코프 autouse, `conftest.py`)가 `alembic upgrade head`로 시드를
이미 넣어 두므로, 여기서는 그 결과를 `db_session`으로 읽기만 한다. 읽는 대상은 **head 상태의
활성 세트**(`load_active_prompt_set`, 프로덕션이 고르는 규칙과 같다)다 — 초기 시드
(`a69cbd40dec8`)가 아니다. 마이그레이션 `b72c33c70240`이 슬롯을 더한 새 published 세트를
만들어 레인마다 published가 여럿이다.

세 갈래:
1. head 활성 세트의 (channel, scope, slot, variant) 집합이 아래 표와 정확히 일치
   (누락·잉여 0).
2. `system` 채널 시드를 scope로 거르고 order로 정렬해 "\\n\\n"으로 이은 결과가
   `system_instruction_for()`의 실제 출력과 바이트 단위로 같다 — 6가지 경우 전부.
3. `UNIQUE(lane) WHERE status='draft'` / `UNIQUE(lane, version) WHERE status='published'`
   부분 인덱스가 실제로 **레인 축으로** 동작한다 —
   같은 레인 두 번째 draft/같은 (레인,버전)의 두 번째 published가 IntegrityError로
   거부되고, 다른 레인이면 **막지 않는다**(`alembic check`가 부분 인덱스의 predicate를
   비교하지 않는 사각지대라 행위 테스트가 유일한 검증 — 근거는 아래 테스트 함수
   docstring의 실측 기록).
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import PromptLane, load_active_prompt_set, system_instruction_for
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import StoryPromptTemplate

# 레인 분리 이후 (channel, scope, slot, variant) 전수는 레인별로 갈린다(story 27 / character 14 /
# publish_filter 16 — 마이그레이션 `a69cbd40dec8`의 `NEW_SECTION_IDS`·`_lanes_for` 배정
# 26/13/16에 마이그레이션 `b72c33c70240`이 story·character generation에 `user_persona`를 한 행씩 더했다).
# system/generation 채널의 `scope='both'` 행은 story·character 두 레인에 사본으로 들어간다.
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
            ("both", "history", ""),
            ("story", "keyword_notes", ""),
            ("story", "shortcut_prompt", ""),
            ("both", "final_frame", ""),
        },
        "stat_judgment": {
            ("story", "stat_defs_intro", ""),
            ("story", "turn_context", ""),
            ("story", "judgment_instruction", ""),
        },
        "ending_judgment": {
            ("story", "history_header", ""),
            ("story", "turn_context", ""),
            ("story", "criteria", ""),
        },
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
            ("both", "history", ""),
            ("both", "final_frame", ""),
        },
        "image_judgment": {
            ("character", "image_list_intro", ""),
            ("character", "turn_context", ""),
            ("character", "judgment_instruction", ""),
        },
    },
    "publish_filter": {
        "publish_filter": {
            ("character", "intro_instruction", ""),
            ("story", "intro_instruction", ""),
            ("both", "name", ""),
            ("both", "one_liner", ""),
            ("character", "intro", ""),
            ("story", "setting_text", ""),
            ("story", "development_example_legacy", ""),
            ("story", "custom_prompt", ""),
            ("story", "rules", ""),
            ("story", "user_goal", ""),
            ("story", "development_examples_pairs", ""),
            ("character", "example_dialogues", ""),
            ("character", "character_prompt", ""),
            ("both", "detail_description", ""),
            ("story", "starting_setups", ""),
            ("both", "verdict_instruction", ""),
        },
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


def _draft_prompt_set(*, lane: str) -> PromptSet:
    return PromptSet(
        id=uuid.uuid4(),
        version=None,
        status="draft",
        lane=lane,
        user_label="사용자",
        story_assistant_label="진행자",
        story_example_label="서술자",
        character_assistant_label="캐릭터",
    )


def _published_prompt_set(*, lane: str, version: str) -> PromptSet:
    return PromptSet(
        id=uuid.uuid4(),
        version=version,
        status="published",
        lane=lane,
        user_label="사용자",
        story_assistant_label="진행자",
        story_example_label="서술자",
        character_assistant_label="캐릭터",
        published_at=datetime.now(UTC),
    )


async def test_draft_partial_unique_index_rejects_second_draft(db_session: AsyncSession) -> None:
    """`UNIQUE(lane) WHERE status='draft'`가 실제로 **같은 레인 안에서** 초안 1개를
    강제하는지 — 같은 레인에 두 번째 draft를 넣으면 거부된다. `alembic check`는 부분
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
    """`UNIQUE(lane, version) WHERE status='published'`가 실제로 **같은 레인 안에서**
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
