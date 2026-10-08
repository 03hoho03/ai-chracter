import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from api.chat.prompt_builder import render_prompt_channel
from api.content.schemas import (
    MEDIA_BOOK_MAX_CELLS,
    RULE_LIST_ADAPTER,
    EndingRuleGroupDraftItem,
    EndingRuleListDraftItem,
    StartingSetupDraftItem,
    count_rules,
)
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.content import Content, ContentVersion
from api.db.models.prompt import PromptSection
from api.db.models.story import (
    Ending,
    KeywordNote,
    MediaBookCell,
    MediaBookPerson,
    MediaBookScene,
    SituationNote,
    StartingSetup,
    StatDef,
    StatRule,
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


REPRESENTATIVE_IMAGE_LABEL = "대표 이미지"


def situational_image_label(position: int) -> str:
    """상황 이미지를 1부터 센 자리로 부르는 이름. 발행 심사 이미지 목록과 어드민 콘텐츠 상세가 함께 쓴다."""
    return f"상황 이미지 {position}"


def media_book_cell_label(person: str, scene: str) -> str:
    """미디어 북 칸 그림을 인물·장면 이름으로 부르는 이름. 발행 심사 이미지 목록과 어드민 콘텐츠 상세가 함께 쓴다."""
    return f"미디어 북 {person}·{scene}"


def _image_lines(labels: Sequence[str]) -> str:
    """심사 프롬프트의 이미지 목록 줄. 번호는 첨부 이미지 안에서의 1부터 센 자리라, 판정 사유가 그 번호나 라벨로
    그림을 가리킬 수 있다."""
    return "\n".join(f"{position}. {label}" for position, label in enumerate(labels, start=1))


def build_character_publish_filter_prompt(*, sections: Sequence[PromptSection], situational_image_count: int) -> str:
    """발행 심사는 첨부 이미지만 본다 — 이미지는 같은 `LLMClient.generate_structured()` 호출의 멀티모달
    파트(`images` 인자)로 전달되고, 프롬프트에는 작가가 쓴 글을 싣지 않고 그 이미지들의 목록 라벨만 싣는다.
    첨부 순서는 대표 이미지 한 장, 그 뒤로 상황 이미지 `situational_image_count` 장이다 — 호출부가 이미지를
    실은 것과 같은 시퀀스에서 개수를 세어야 라벨과 그림이 짝을 이룬다."""
    labels = [
        REPRESENTATIVE_IMAGE_LABEL,
        *(situational_image_label(index) for index in range(1, situational_image_count + 1)),
    ]
    return render_prompt_channel(
        sections, channel="publish_filter", scope="character", values={"image_lines": _image_lines(labels)}
    )


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
    stat_defs: Sequence[StatDef],
    stat_rules: Sequence[StatRule],
    situation_notes: Sequence[SituationNote],
    dangling_situation_note_paths: Sequence[str],
) -> list[str]:
    """Mirrors `validate_character_publish`'s
    shape. `endings_by_setup_id` is keyed by `StartingSetup.id` (physical) since that's how the
    router naturally loads them (one query per setup) — the caller passes in whatever it already
    fetched, this function does no DB I/O itself.

    미디어 북은 자동저장이 이미 칸 수와 축 참조를 막지만 발행이 마지막 관문이다. 칸 수 상한을 넘으면
    `mediaBook.cells`, 그 버전에 없는 인물·장면을 가리키는 칸이 하나라도 있으면 `mediaBook.orphanCells` 를 한 번씩
    알린다 — 축 참조에는 FK 가 없고, 그런 칸은 이름이 없어 심사 이미지 라벨도 만들 수 없다. 고아 칸은 빌더 화면에 나오지
    않아 칸 하나하나를 가리킬 수 없고, 미디어 북을 한 번 다시 저장하면 지워진다.

    키워드북은 자동저장이 빈 노트(노트 추가 직후)를 받아 주므로 여기서 막는다. 상시가 아닌 노트에 공백 아닌 키워드가
    하나도 없으면 `keywordNotes.triggerKeywords`(열릴 길이 없다), 정보가 공백뿐인 노트가 있으면 `keywordNotes.infoText`
    (실려도 빈 줄이다)를 노트 수와 상관없이 한 번씩 알린다 — 어느 노트인지는 빌더 폼 검증이 노트 자리에서 먼저 보여 준다.

    엔딩 규칙이나 엔딩의 우선 스탯이 같은 시작설정에 없는 스탯을 가리키면(`dangling_stat_rule_paths`, 호출부가
    `setup_dangling_stat_rule_paths`·`setup_dangling_priority_stat_paths` 로 구한다) `endings.statRules` 를 한 번 알린다.
    규칙은 영영 참이 될 수 없고, 우선 스탯은 비교에서 늘 빠진다. 키를 하나로 두는 것은 둘 다 빌더의 같은 엔딩 자리에서
    고치기 때문이다. 초안 저장이 같은 검사로 경로까지 알려 막으므로, 여기는 그 검사 전에 저장된 초안, 우선 스탯을 보내지
    않는 옛 화면이 스탯만 지운 초안, API 직접 호출을 막는 마지막 관문이다.

    스탯(`stat_defs`, 모든 시작설정의 것)은 최소 < 최대, 최소 ≤ 초기 ≤ 최대여야 하고, 어긋난 스탯이 하나라도 있으면
    `stats.range` 를 한 번 알린다. 대화는 방을 열 때 초기값을 그대로 두고 이후 변화부터 범위로 잘라 쓴다 — 범위 밖
    초기값은 첫 변화에서 경계로 튀고, 뒤집힌 범위에서는 어떤 변화든 최대값 하나로 붙는다. 초안 저장은 이 검사를 하지 않는다 — 이미 그렇게 저장된 초안이 있어 저장에서 막으면 그 초안의
    자동저장이 편집마다 실패한다. 빌더 폼 검증이 어느 칸인지를 먼저 보여 주므로 여기는 API 직접 호출을 막는 관문이다.

    변화 방향·한 턴 최대 폭도 같은 이유로 발행만 검사한다. 턴당 변화가 있는 스탯에 둘 중 하나라도 걸려 있으면
    `stats.changeLimitWithCounter` 를 알린다 — 그 스탯은 판정을 받지 않아 옵션이 아무 일도 하지 않는데, 작가는 걸었다고
    믿게 된다. 최대 폭이 0 이하이면 `stats.maxChangePerTurn` 을 알린다(빈 값이 "제한 없음"이다). 두 키 모두 어긋난
    스탯 수와 상관없이 한 번씩이다.

    스탯 규칙(`stat_rules`, 모든 스탯의 것, `StatRule.stat_def_id` 가 `stat_defs` 의 `id` 를 가리킨다)이 턴당 변화가 있는
    스탯에 달려 있으면 `stats.rulesWithCounter` 를 같은 결로 한 번 알린다 — 그 스탯은 판정을 받지 않아 규칙이 발동할 일이
    없는데, 작가는 걸었다고 믿게 된다. 규칙의 개수·조건 길이·폭은 초안 저장이 막는다.

    상황 노트(`situation_notes`, 모든 시작설정의 것)는 자동저장이 빈 노트를 받아 주므로 여기서 막는다. 조건 규칙이
    하나도 없는 노트(빈 그룹만 있는 노트 포함)가 있으면 `situationNotes.emptyConditionRules` — 조건 없는 상시 지시는
    스토리 설정의 자리다. 본문이 공백뿐인 노트가 있으면 `situationNotes.infoText`. 조건이 같은 시작설정에 없는 스탯을 가리키면(`dangling_situation_note_paths`,
    호출부가 `setup_dangling_situation_note_paths` 로 구한다) `situationNotes.conditionRules` — 엔딩의
    `endings.statRules` 와 같은 관문이고, 키를 따로 두는 것은 빌더가 작가를 엔딩이 아니라 상황 노트 자리로 보내게
    하려는 것이다. 세 키 모두 노트 수와 상관없이 한 번씩이다.
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
    if any(
        not (stat.min_value < stat.max_value and stat.min_value <= stat.initial_value <= stat.max_value)
        for stat in stat_defs
    ):
        missing.append("stats.range")
    if any(
        stat.per_turn_delta is not None
        and (stat.change_direction not in (None, "both") or stat.max_change_per_turn is not None)
        for stat in stat_defs
    ):
        missing.append("stats.changeLimitWithCounter")
    counter_stat_ids = {stat.id for stat in stat_defs if stat.per_turn_delta is not None}
    if any(rule.stat_def_id in counter_stat_ids for rule in stat_rules):
        missing.append("stats.rulesWithCounter")
    if any(stat.max_change_per_turn is not None and stat.max_change_per_turn <= 0 for stat in stat_defs):
        missing.append("stats.maxChangePerTurn")

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

    if any(count_rules(RULE_LIST_ADAPTER.validate_python(note.condition_rules)) == 0 for note in situation_notes):
        missing.append("situationNotes.emptyConditionRules")
    if any(not note.info_text.strip() for note in situation_notes):
        missing.append("situationNotes.infoText")
    if dangling_situation_note_paths:
        missing.append("situationNotes.conditionRules")

    if not version.detail_description:
        missing.append("description")
    if content.genre_id is None:
        missing.append("genreId")
    if content.target is None:
        missing.append("target")
    return missing


def _dangling_rule_paths(
    owners_path: str,
    rules_field: str,
    stat_ids: Collection[uuid.UUID],
    owners_rules: Sequence[Sequence[EndingRuleListDraftItem]],
) -> list[str]:
    """규칙 목록을 가진 항목들(`owners_path[j]`)에서 `stat_ids` 에 없는 스탯을 가리키는 규칙의 필드 경로.
    경로는 `{owners_path}[j].{rules_field}[k](.rules[n]).statId` 꼴이다."""
    dangling: list[str] = []
    for owner_index, rule_items in enumerate(owners_rules):
        for rule_index, rule_item in enumerate(rule_items):
            path = f"{owners_path}[{owner_index}].{rules_field}[{rule_index}]"
            if isinstance(rule_item, EndingRuleGroupDraftItem):
                for nested_index, nested_item in enumerate(rule_item.rules):
                    if nested_item.stat_id not in stat_ids:
                        dangling.append(f"{path}.rules[{nested_index}].statId")
            elif rule_item.stat_id not in stat_ids:
                dangling.append(f"{path}.statId")
    return dangling


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
    return _dangling_rule_paths(f"startingSetups[{setup_index}].endings", "statRules", stat_ids, endings_rules)


def setup_dangling_situation_note_paths(
    setup_index: int,
    stat_ids: Collection[uuid.UUID],
    notes_rules: Sequence[Sequence[EndingRuleListDraftItem]],
) -> list[str]:
    """`setup_dangling_stat_rule_paths` 와 같은 검사를 상황 노트의 조건에 한다. 그런 조건은 영영 참이 될 수 없어
    노트가 조용히 안 실린다. 경로는 `startingSetups[i].situationNotes[j].conditionRules[k](.rules[n]).statId` 꼴이다.
    엔딩과 경로를 따로 내는 이유는 빌더가 엔딩 조건과 상황 노트 조건을 다른 자리에서 고치게 하기 때문이다."""
    return _dangling_rule_paths(
        f"startingSetups[{setup_index}].situationNotes", "conditionRules", stat_ids, notes_rules
    )


def setup_dangling_priority_stat_paths(
    setup_index: int,
    stat_ids: Collection[uuid.UUID],
    priority_stat_ids: Sequence[uuid.UUID | None],
) -> list[str]:
    """시작설정 하나에서, 그 시작설정의 스탯(`stat_ids`, entity_id)에 없는 스탯을 우선 스탯으로 고른 엔딩의 필드 경로.
    `priority_stat_ids` 는 엔딩 목록 순서의 우선 스탯이다(비운 엔딩은 None).

    엔딩 규칙의 스탯 참조와 같이 FK 가 없어 스탯을 지운 뒤에도 남을 수 있다. 대화는 그 엔딩을 우선 스탯 비교에서 빼고
    우선 스탯이 없는 엔딩처럼 판정하므로, 작가가 고른 비교가 조용히 사라진다. 엔딩 규칙과 같은 자리에서 막는다(초안 저장 422 의
    같은 코드, 발행의 같은 키). 경로는 빌더 폼과 같은 `startingSetups[i].endings[j].priorityStatId` 꼴이다."""
    return [
        f"startingSetups[{setup_index}].endings[{ending_index}].priorityStatId"
        for ending_index, priority_stat_id in enumerate(priority_stat_ids)
        if priority_stat_id is not None and priority_stat_id not in stat_ids
    ]


def draft_dangling_stat_rule_paths(starting_setups: Sequence[StartingSetupDraftItem]) -> list[str]:
    """초안 페이로드 전체에 `setup_dangling_stat_rule_paths` 와 `setup_dangling_priority_stat_paths` 를 적용한다(초안
    저장과 시드가 쓴다). 시작설정마다 규칙 경로 뒤에 우선 스탯 경로가 온다."""
    paths: list[str] = []
    for setup_index, setup_item in enumerate(starting_setups):
        stat_ids = {stat_item.id for stat_item in setup_item.stat_defs}
        paths += setup_dangling_stat_rule_paths(
            setup_index, stat_ids, [ending_item.stat_rules for ending_item in setup_item.endings]
        )
        paths += setup_dangling_priority_stat_paths(
            setup_index, stat_ids, [ending_item.priority_stat_id for ending_item in setup_item.endings]
        )
    return paths


def draft_dangling_situation_note_paths(starting_setups: Sequence[StartingSetupDraftItem]) -> list[str]:
    """초안 페이로드 전체에 `setup_dangling_situation_note_paths` 를 적용한다(초안 저장과 시드가 쓴다)."""
    return [
        path
        for setup_index, setup_item in enumerate(starting_setups)
        for path in setup_dangling_situation_note_paths(
            setup_index,
            {stat_item.id for stat_item in setup_item.stat_defs},
            [note_item.condition_rules for note_item in setup_item.situation_notes],
        )
    ]


@dataclass(frozen=True)
class MediaBookFilterCell:
    """발행 심사 이미지 목록에서 미디어 북 칸 그림 하나를 가리키는 이름. 대화 중 칸 판정 후보(`MediaCellCandidate`)와
    따로 두는 이유는 심사에 필요한 것이 라벨뿐이라서다 — 칸의 상황 설명·해금 힌트는 심사하지 않는다."""

    person: str
    scene: str


def build_story_publish_filter_prompt(
    *, sections: Sequence[PromptSection], media_cells: Sequence[MediaBookFilterCell]
) -> str:
    """발행 심사는 첨부 이미지만 본다 — 첨부는 대표 이미지와, 그 뒤로 미디어 북 칸마다 축소본 한 장씩이고 호출부가
    같은 `generate_structured` 호출의 `images` 인자로 함께 전달한다. 프롬프트에는 작가가 쓴 글을 싣지 않고 이미지
    목록 라벨만 싣는다. 칸 그림은 `media_cells` 와 같은 순서로 실어야 `미디어 북 {인물}·{장면}` 라벨과 짝이 맞는다."""
    labels = [REPRESENTATIVE_IMAGE_LABEL, *(media_book_cell_label(cell.person, cell.scene) for cell in media_cells)]
    return render_prompt_channel(
        sections, channel="publish_filter", scope="story", values={"image_lines": _image_lines(labels)}
    )
