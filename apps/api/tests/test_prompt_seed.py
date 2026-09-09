"""prompt-db-goal-prompt.md §6 (1단계) — 마이그레이션이 심은 초기 프롬프트 세트 검증.

`_migrated_schema`(세션 스코프 autouse, `conftest.py`)가 `alembic upgrade head`로 시드를
이미 넣어 두므로, 여기서는 그 결과를 `db_session`으로 읽기만 한다 — 이 단계는 렌더러가
없으므로(2단계 범위) `PromptSet`/`PromptSection`을 실제로 소비하는 코드는 아직 없다.

세 갈래:
1. 시드된 (channel, scope, slot, variant) 집합이 prompt-db-progress.md §B와 정확히 일치
   (누락·잉여 0).
2. `system` 채널 시드를 scope로 거르고 order로 정렬해 "\\n\\n"으로 이은 결과가
   `system_instruction_for()`의 실제 출력과 바이트 단위로 같다(D-13) — 6가지 경우 전부.
3. `UNIQUE(status) WHERE status='draft'` 부분 인덱스가 실제로 동작한다 — 두 번째 draft
   INSERT가 IntegrityError로 거부된다(`alembic check`가 비교하지 않는 사각지대라 행위
   테스트가 유일한 검증).
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import system_instruction_for
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import StoryPromptTemplate

# prompt-db-progress.md §B — 채널별 (scope, slot, variant) 전수. 누락·잉여를 여기와 대조한다.
_EXPECTED_SLOTS: dict[str, set[tuple[str, str, str]]] = {
    "system": {
        ("story", "self_definition", ""),
        ("character", "self_definition", ""),
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
        ("character", "character_prompt", ""),
        ("story", "base_content", ""),
        ("story", "base_content", "custom"),
        ("character", "example_dialogues", ""),
        ("story", "rules", ""),
        ("story", "user_goal", ""),
        ("story", "development_examples", ""),
        ("story", "prologue", ""),
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
    "image_judgment": {
        ("character", "image_list_intro", ""),
        ("character", "turn_context", ""),
        ("character", "judgment_instruction", ""),
    },
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
}


async def _active_sections(db_session: AsyncSession) -> list[PromptSection]:
    active_set_id = (
        await db_session.execute(select(PromptSet.id).where(PromptSet.status == "published"))
    ).scalar_one()
    result = await db_session.execute(
        select(PromptSection).where(PromptSection.prompt_set_id == active_set_id)
    )
    return list(result.scalars())


async def test_seeded_slot_set_matches_spec_exactly(db_session: AsyncSession) -> None:
    sections = await _active_sections(db_session)

    actual: dict[str, set[tuple[str, str, str]]] = {}
    for section in sections:
        actual.setdefault(section.channel, set()).add((section.scope, section.slot, section.variant))

    assert actual == _EXPECTED_SLOTS

    expected_total = sum(len(slots) for slots in _EXPECTED_SLOTS.values())
    assert len(sections) == expected_total == 48


def _reconstruct_system_instruction(
    sections: list[PromptSection], *, is_story_chat: bool, template: StoryPromptTemplate | None
) -> str:
    """prompt-db-goal-prompt.md §4-2 렌더링 규약 — scope로 거르고 order로 정렬해 "\\n\\n"으로
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
    ("is_story_chat", "template"),
    [
        (False, None),
        (True, StoryPromptTemplate.BASIC),
        (True, StoryPromptTemplate.EMOTIONAL),
        (True, StoryPromptTemplate.SIMULATION),
        (True, StoryPromptTemplate.CUSTOM),
        (True, None),
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
    db_session: AsyncSession, is_story_chat: bool, template: StoryPromptTemplate | None
) -> None:
    sections = await _active_sections(db_session)
    reconstructed = _reconstruct_system_instruction(
        sections, is_story_chat=is_story_chat, template=template
    )
    expected = system_instruction_for(sections, is_story_chat=is_story_chat, template=template)
    assert reconstructed == expected


async def test_draft_partial_unique_index_rejects_second_draft(db_session: AsyncSession) -> None:
    """`UNIQUE(status) WHERE status='draft'`가 실제로 전역 초안 1개를 강제하는지 —
    `alembic check`는 부분 인덱스의 술어를 비교하지 않으므로 행위 테스트가 유일한 검증이다."""
    db_session.add(
        PromptSet(
            id=uuid.uuid4(),
            version=None,
            status="draft",
            user_label="사용자",
            story_assistant_label="진행자",
            story_example_label="서술자",
            character_assistant_label="캐릭터",
        )
    )
    await db_session.flush()

    db_session.add(
        PromptSet(
            id=uuid.uuid4(),
            version=None,
            status="draft",
            user_label="사용자",
            story_assistant_label="진행자",
            story_example_label="서술자",
            character_assistant_label="캐릭터",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_published_version_partial_unique_index_rejects_duplicate_version(
    db_session: AsyncSession,
) -> None:
    """`UNIQUE(version) WHERE status='published'`가 실제로 게시 버전 중복을 막는지 —
    `ix_prompt_sets_draft`와 정확히 같은 이유로(부분 인덱스 predicate는 `alembic check`가
    비교하지 않는다) 행위 테스트가 유일한 검증이다. dev Postgres에서 이 인덱스를 잠시
    지운 뒤 같은 시나리오를 재현하면 두 번째 INSERT가 에러 없이 성공한다 — 이 인덱스가
    없으면 이 테스트가 실패한다는 것을 그렇게 직접 확인했다."""
    db_session.add(
        PromptSet(
            id=uuid.uuid4(),
            version="9001",
            status="published",
            user_label="사용자",
            story_assistant_label="진행자",
            story_example_label="서술자",
            character_assistant_label="캐릭터",
            published_at=datetime.now(UTC),
        )
    )
    await db_session.flush()

    db_session.add(
        PromptSet(
            id=uuid.uuid4(),
            version="9001",
            status="published",
            user_label="사용자",
            story_assistant_label="진행자",
            story_example_label="서술자",
            character_assistant_label="캐릭터",
            published_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_published_version_partial_unique_index_allows_different_versions(
    db_session: AsyncSession,
) -> None:
    """반대편 확인 — `version`이 다르면 인덱스가 과하게 막지 않는다. 여러 `published`
    행이 서로 다른 버전으로 공존할 수 있어야 버전 이력(D-3)이 성립한다."""
    db_session.add(
        PromptSet(
            id=uuid.uuid4(),
            version="9002",
            status="published",
            user_label="사용자",
            story_assistant_label="진행자",
            story_example_label="서술자",
            character_assistant_label="캐릭터",
            published_at=datetime.now(UTC),
        )
    )
    db_session.add(
        PromptSet(
            id=uuid.uuid4(),
            version="9003",
            status="published",
            user_label="사용자",
            story_assistant_label="진행자",
            story_example_label="서술자",
            character_assistant_label="캐릭터",
            published_at=datetime.now(UTC),
        )
    )
    await db_session.flush()
