import uuid
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from api.chat.prompt_builder import render_prompt_channel
from api.db.models.character import CharacterVersionDetail
from api.db.models.content import Content, ContentVersion
from api.db.models.prompt import PromptSection, PromptSet
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
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
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

    `[예시 대화]` 목록의 화자 라벨은 코드가 조립하는 줄 안에서도 `prompt_set`에서 읽는다
    (prompt-db-goal-prompt.md §4-4).
    """
    dialogue_lines = "\n".join(
        f"- {prompt_set.user_label}: {pair['userLine']} / {prompt_set.character_assistant_label}: "
        f"{pair['characterLine']}"
        for pair in example_dialogues
    )
    values = {
        "name": name,
        "one_liner": one_liner,
        "intro": intro,
        "dialogue_lines": dialogue_lines,
        "character_prompt": character_prompt,
        "detail_description": detail_description,
    }
    return render_prompt_channel(sections, channel="publish_filter", scope="character", values=values)


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
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
    name: str,
    one_liner: str,
    setting_text: str | None,
    development_example: str | None,
    custom_prompt: str | None,
    development_examples: list[dict[str, Any]],
    user_goal: str | None,
    rules: str | None,
    detail_description: str,
    starting_setups: Sequence[StartingSetup],
) -> str:
    """techspec-backend-content.md §1.3. 스토리는 상황별 이미지가 없어 첨부 이미지는 대표
    이미지 하나뿐이다(techspec-db-schema.md §5) — 그 이미지는 호출부가 같은 `generate_structured`
    호출의 `images` 인자로 함께 전달한다.

    chat-goal-prompt.md §8: `developmentExamples`/`userGoal`/`rules`도 창작자가 적는 텍스트라
    `development_example`과 함께 심사 대상에 넣는다(D-19의 발행 필수화 제외와는 별개 — 값이
    있으면 걸러야 한다). `[전개 예시(쌍)]` 목록의 화자 라벨은 코드가 조립하는 줄 안에서도
    `prompt_set`에서 읽는다(§4-4) — 전개 예시 자리는 `story_example_label`("서술자")을 쓴다(§1-1).
    """
    example_lines = "\n".join(
        f"{prompt_set.user_label}: {pair['userLine']}\n{prompt_set.story_example_label}: {pair['assistantLine']}"
        for pair in development_examples
    )
    setup_lines = "\n".join(f"- {setup.name}: {setup.prologue}" for setup in starting_setups)
    values = {
        "name": name,
        "one_liner": one_liner,
        "setting_text": setting_text or "",
        "development_example": development_example or "",
        "custom_prompt": custom_prompt or "",
        "rules": rules or "",
        "user_goal": user_goal or "",
        "example_lines": example_lines,
        "detail_description": detail_description,
        "setup_lines": setup_lines,
    }
    return render_prompt_channel(sections, channel="publish_filter", scope="story", values=values)
