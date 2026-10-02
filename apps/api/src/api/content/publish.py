import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from api.chat.prompt_builder import render_prompt_channel
from api.content.schemas import (
    MEDIA_BOOK_MAX_CELLS,
    EndingRuleGroupDraftItem,
    EndingRuleListDraftItem,
    StartingSetupDraftItem,
)
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.content import Content, ContentVersion
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import (
    Ending,
    KeywordNote,
    MediaBookCell,
    MediaBookPerson,
    MediaBookScene,
    StartingSetup,
    StoryPromptTemplate,
    StoryVersionDetail,
)


def validate_character_publish(
    content: Content,
    version: ContentVersion,
    detail: CharacterVersionDetail,
    situational_images: Sequence[SituationalImage],
) -> list[str]:
    """Pure required-field check for
    character publish — DB I/O happens in the router, this only inspects already-loaded
    rows (same split as api/chat/stats.py's apply_stat_changes). Returns the camelCase
    field names FE would recognize as missing; empty list means the draft is publishable.

    `situationalImages` is reported once when any row still has no image: autosave creates
    the row before the image is uploaded, and a published row without one is a slot the chat
    can never show.
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
    if any(image.image_asset_id is None for image in situational_images):
        missing.append("situationalImages")
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
    """텍스트 검열 지시문 — 첨부된 이미지(대표이미지/
    상황별이미지)는 같은 LLMClient.generate_structured() 호출의 멀티모달 파트로 함께
    전달되므로(images 인자), 이 프롬프트가 그 이미지들도 함께 심사하도록 명시한다.

    `[예시 대화]` 목록의 화자 라벨은 코드가 조립하는 줄 안에서도 `prompt_set`에서 읽는다.
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
    *,
    media_book_people: Sequence[MediaBookPerson],
    media_book_scenes: Sequence[MediaBookScene],
    media_book_cells: Sequence[MediaBookCell],
    keyword_notes: Sequence[KeywordNote],
    dangling_stat_rule_paths: Sequence[str],
) -> list[str]:
    """Mirrors `validate_character_publish`'s
    shape. `endings_by_setup_id` is keyed by `StartingSetup.id` (physical) since that's how the
    router naturally loads them (one query per setup) — the caller passes in whatever it already
    fetched, this function does no DB I/O itself.

    미디어 북은 자동저장이 이미 칸 수와 축 참조를 막지만 발행이 마지막 관문이다. 칸 수 상한을 넘으면
    `mediaBook.cells`, 그 버전에 없는 인물·장면을 가리키는 칸이 하나라도 있으면 `mediaBook.orphanCells` 를 한 번씩
    알린다 — 축 참조에는 FK 가 없고, 그런 칸은 이름이 없어 심사 줄도 만들 수 없다. 고아 칸은 빌더 화면에 나오지
    않아 칸 하나하나를 가리킬 수 없고, 미디어 북을 한 번 다시 저장하면 지워진다.

    키워드북은 자동저장이 빈 노트(노트 추가 직후)를 받아 주므로 여기서 막는다. 상시가 아닌 노트에 공백 아닌 키워드가
    하나도 없으면 `keywordNotes.triggerKeywords`(열릴 길이 없다), 정보가 공백뿐인 노트가 있으면 `keywordNotes.infoText`
    (실려도 빈 줄이다)를 노트 수와 상관없이 한 번씩 알린다 — 어느 노트인지는 빌더 폼 검증이 노트 자리에서 먼저 보여 준다.

    엔딩 규칙이 같은 시작설정에 없는 스탯을 가리키면(`dangling_stat_rule_paths`, 호출부가 `setup_dangling_stat_rule_paths`
    로 구한다) `endings.statRules` 를 한 번 알린다. 그 조건은 영영 참이 될 수 없다. 초안 저장이 같은 검사로 경로까지
    알려 막으므로, 여기는 그 검사 전에 저장된 초안과 API 직접 호출을 막는 마지막 관문이다.
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
    if dangling_stat_rule_paths:
        missing.append("endings.statRules")

    if len(media_book_cells) > MEDIA_BOOK_MAX_CELLS:
        missing.append("mediaBook.cells")
    person_ids = {person.entity_id for person in media_book_people}
    scene_ids = {scene.entity_id for scene in media_book_scenes}
    if any(
        cell.person_entity_id not in person_ids or cell.scene_entity_id not in scene_ids for cell in media_book_cells
    ):
        missing.append("mediaBook.orphanCells")

    if any(not note.always_on and not any(k.strip() for k in note.trigger_keywords) for note in keyword_notes):
        missing.append("keywordNotes.triggerKeywords")
    if any(not note.info_text.strip() for note in keyword_notes):
        missing.append("keywordNotes.infoText")

    if not version.detail_description:
        missing.append("description")
    if content.genre_id is None:
        missing.append("genreId")
    if content.target is None:
        missing.append("target")
    return missing


def setup_dangling_stat_rule_paths(
    setup_index: int,
    stat_ids: Collection[uuid.UUID],
    endings_rules: Sequence[Sequence[EndingRuleListDraftItem]],
) -> list[str]:
    """시작설정 하나에서, 그 시작설정의 스탯(`stat_ids`, entity_id)에 없는 스탯을 가리키는 엔딩 규칙의 필드 경로.

    규칙의 스탯 참조에는 FK 가 없어 스탯을 지운 뒤 남은 규칙을 저장이 받아 준다. 대화는 그 항목을 거짓으로 보고
    계속되므로, 어긋난 규칙은 엔딩이 조용히 영영 안 열리는 형태로만 드러난다. 그래서 초안 저장·발행·시드가 이 검사로
    막는다. 경로는 빌더 폼과 같은 `startingSetups[i].endings[j].statRules[k](.rules[n]).statId` 꼴이다.
    """
    dangling: list[str] = []
    for ending_index, rule_items in enumerate(endings_rules):
        for rule_index, rule_item in enumerate(rule_items):
            path = f"startingSetups[{setup_index}].endings[{ending_index}].statRules[{rule_index}]"
            if isinstance(rule_item, EndingRuleGroupDraftItem):
                for nested_index, nested_item in enumerate(rule_item.rules):
                    if nested_item.stat_id not in stat_ids:
                        dangling.append(f"{path}.rules[{nested_index}].statId")
            elif rule_item.stat_id not in stat_ids:
                dangling.append(f"{path}.statId")
    return dangling


def draft_dangling_stat_rule_paths(starting_setups: Sequence[StartingSetupDraftItem]) -> list[str]:
    """초안 페이로드 전체에 `setup_dangling_stat_rule_paths` 를 적용한다(초안 저장과 시드가 쓴다)."""
    return [
        path
        for setup_index, setup_item in enumerate(starting_setups)
        for path in setup_dangling_stat_rule_paths(
            setup_index,
            {stat_item.id for stat_item in setup_item.stat_defs},
            [ending_item.stat_rules for ending_item in setup_item.endings],
        )
    ]


@dataclass(frozen=True)
class MediaBookFilterCell:
    """발행 심사에 싣는 미디어 북 칸 하나의 글. 대화 중 칸 판정 후보(`MediaCellCandidate`)와 따로 두는 이유는
    해금 힌트다 — 힌트는 보관함에서 다른 플레이어에게 보이는 글이라 심사하지만, 판정 근거는 아니라 판정에는 싣지
    않는다."""

    person: str
    scene: str
    situation_description: str
    unlock_hint: str


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
    media_cells: Sequence[MediaBookFilterCell],
) -> str:
    """첨부 이미지는 대표 이미지와, 그 뒤로 미디어 북 칸마다 축소본 한 장씩이다 — 호출부가 같은
    `generate_structured` 호출의 `images` 인자로 함께 전달한다. 칸 그림은 `media_cells` 와 같은 순서로 실어야
    프롬프트의 칸 줄(`- 인물/장면: 상황 설명 (해금 힌트: …)`)과 짝이 맞는다. 칸 이름·상황 설명·해금 힌트도 작성자가
    쓴 글이라 심사한다. 상황 설명·힌트가 빈 칸은 그 부분을 빼고(빈 값을 내용처럼 보이게 하지 않는다), 칸이 없으면
    값이 비어 섹션째 빠진다.

    `developmentExamples`/`userGoal`/`rules`도 창작자가 적는 텍스트라
    `development_example`과 함께 심사 대상에 넣는다(발행 필수 항목이 아니라는 것과는 별개 — 값이
    있으면 걸러야 한다). `[전개 예시(쌍)]` 목록의 화자 라벨은 코드가 조립하는 줄 안에서도
    `prompt_set`에서 읽는다 — 전개 예시 자리는 `story_example_label`("서술자")을 쓴다.
    """
    example_lines = "\n".join(
        f"{prompt_set.user_label}: {pair['userLine']}\n{prompt_set.story_example_label}: {pair['assistantLine']}"
        for pair in development_examples
    )
    setup_lines = "\n".join(f"- {setup.name}: {setup.prologue}" for setup in starting_setups)
    media_book_lines = "\n".join(
        f"- {cell.person}/{cell.scene}"
        + (f": {cell.situation_description}" if cell.situation_description else "")
        + (f" (해금 힌트: {cell.unlock_hint})" if cell.unlock_hint else "")
        for cell in media_cells
    )
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
        "media_book_lines": media_book_lines,
    }
    return render_prompt_channel(sections, channel="publish_filter", scope="story", values=values)
