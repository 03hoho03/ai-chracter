import uuid
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from api.db.models.character import CharacterVersionDetail
from api.db.models.content import Content, ContentVersion
from api.db.models.story import Ending, StartingSetup, StoryPromptTemplate, StoryVersionDetail


def validate_character_publish(
    content: Content, version: ContentVersion, detail: CharacterVersionDetail
) -> list[str]:
    """techspec-backend-content.md §1.2/§1.3 (US-083). Pure required-field check for
    character publish — DB I/O happens in the router, this only inspects already-loaded
    rows (same split as api/chat/stats.py's apply_stat_changes). Returns the camelCase
    field names FE would recognize as missing; empty list means the draft is publishable.
    """
    missing: list[str] = []
    if not detail.name:
        missing.append("name")
    if not detail.one_liner:
        missing.append("oneLiner")
    if detail.thumbnail_asset_id is None:
        missing.append("thumbnailAssetId")
    if not detail.intro:
        missing.append("intro")
    if not detail.character_prompt:
        missing.append("characterPrompt")
    if not version.detail_description:
        missing.append("description")
    if content.genre_id is None:
        missing.append("genreId")
    if content.target is None:
        missing.append("target")
    return missing


class PublishFilterResult(BaseModel):
    """techspec-backend-content.md §1.3 판단용 response_schema — 발행 시 자동 필터."""

    passed: bool
    reason: str | None


def build_character_publish_filter_prompt(
    *,
    name: str,
    one_liner: str,
    intro: str,
    example_dialogues: list[dict[str, Any]],
    character_prompt: str,
    detail_description: str,
) -> str:
    """techspec-backend-content.md §1.3. 텍스트 검열 지시문 — 첨부된 이미지(대표이미지/
    상황별이미지)는 같은 LLMClient.generate_structured() 호출의 멀티모달 파트로 함께
    전달되므로(images 인자), 이 프롬프트가 그 이미지들도 함께 심사하도록 명시한다.
    """
    sections = [
        "다음은 사용자가 발행하려는 AI 캐릭터의 등록 정보다. 아래 텍스트와 함께 첨부된 "
        "이미지(대표 이미지 및 상황별 이미지가 있다면 그것들도 포함)를 모두 심사해, 선정성/"
        "폭력성/혐오 표현/불법 콘텐츠 등 서비스에 부적절한 내용이 있는지 판단하라.",
        f"[이름]\n{name}",
        f"[한줄소개]\n{one_liner}",
        f"[인트로]\n{intro}",
    ]

    if example_dialogues:
        dialogue_lines = "\n".join(
            f"- 사용자: {pair['userLine']} / 캐릭터: {pair['characterLine']}"
            for pair in example_dialogues
        )
        sections.append(f"[예시 대화]\n{dialogue_lines}")

    sections.append(f"[캐릭터 프롬프트]\n{character_prompt}")
    sections.append(f"[상세 설명]\n{detail_description}")
    sections.append(
        "부적절한 내용이 없으면 passed=true, reason은 null로 응답하라. 부적절한 내용이 있으면 "
        "passed=false와 함께 어떤 부분이 어떤 이유로 문제인지 reason에 한국어로 간결히 설명하라."
    )

    return "\n\n".join(sections)


def validate_story_publish(
    content: Content,
    version: ContentVersion,
    detail: StoryVersionDetail,
    starting_setups: Sequence[StartingSetup],
    endings_by_setup_id: dict[uuid.UUID, Sequence[Ending]],
) -> list[str]:
    """techspec-backend-content.md §1.2/§1.3 (US-085), mirrors `validate_character_publish`'s
    shape. `endings_by_setup_id` is keyed by `StartingSetup.id` (physical) since that's how the
    router naturally loads them (one query per setup) — the caller passes in whatever it already
    fetched, this function does no DB I/O itself.
    """
    missing: list[str] = []
    if not detail.name:
        missing.append("name")
    if not detail.one_liner:
        missing.append("oneLiner")
    if detail.thumbnail_asset_id is None:
        missing.append("thumbnailAssetId")
    if detail.prompt_template == StoryPromptTemplate.CUSTOM:
        if not detail.custom_prompt:
            missing.append("customPrompt")
    elif not detail.setting_text:
        missing.append("settingText")

    if not starting_setups:
        missing.append("startingSetups")
    for setup_index, setup in enumerate(starting_setups):
        if not setup.name:
            missing.append(f"startingSetups[{setup_index}].name")
        if not setup.prologue:
            missing.append(f"startingSetups[{setup_index}].prologue")
        for ending_index, ending in enumerate(endings_by_setup_id.get(setup.id, [])):
            if ending.turn_count_gate < 10:
                missing.append(f"startingSetups[{setup_index}].endings[{ending_index}].turnCountGate")

    if not version.detail_description:
        missing.append("description")
    if content.genre_id is None:
        missing.append("genreId")
    if content.target is None:
        missing.append("target")
    return missing


def build_story_publish_filter_prompt(
    *,
    name: str,
    one_liner: str,
    setting_text: str | None,
    development_example: str | None,
    custom_prompt: str | None,
    detail_description: str,
    starting_setups: Sequence[StartingSetup],
) -> str:
    """techspec-backend-content.md §1.3. 스토리는 상황별 이미지가 없어 첨부 이미지는 대표
    이미지 하나뿐이다(techspec-db-schema.md §5) — 그 이미지는 호출부가 같은 `generate_structured`
    호출의 `images` 인자로 함께 전달한다."""
    sections = [
        "다음은 사용자가 발행하려는 스토리 콘텐츠의 등록 정보다. 아래 텍스트와 함께 첨부된 "
        "이미지(대표 이미지)를 모두 심사해, 선정성/폭력성/혐오 표현/불법 콘텐츠 등 서비스에 부적절한 "
        "내용이 있는지 판단하라.",
        f"[이름]\n{name}",
        f"[한줄소개]\n{one_liner}",
    ]

    if setting_text:
        sections.append(f"[세계관/설정]\n{setting_text}")
    if development_example:
        sections.append(f"[전개 예시]\n{development_example}")
    if custom_prompt:
        sections.append(f"[커스텀 프롬프트]\n{custom_prompt}")

    sections.append(f"[상세 설명]\n{detail_description}")

    if starting_setups:
        setup_lines = "\n".join(f"- {setup.name}: {setup.prologue}" for setup in starting_setups)
        sections.append(f"[시작 설정]\n{setup_lines}")

    sections.append(
        "부적절한 내용이 없으면 passed=true, reason은 null로 응답하라. 부적절한 내용이 있으면 "
        "passed=false와 함께 어떤 부분이 어떤 이유로 문제인지 reason에 한국어로 간결히 설명하라."
    )

    return "\n\n".join(sections)
