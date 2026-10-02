"""설계 장면(`data/tutorial_filmclub.json`) → 판정 호출 입력.

장면은 시드 작품(조감독 튜토리얼 스토리와 튜토리얼 캐릭터 유나) 위에 정답이 분명하도록 쓴 대화다. 작품 값(스탯 정의·
엔딩 판정 문구·상황 이미지 노출 조건·발행 심사 글)은 시드 JSON 을 시드 로더로 읽어 쓰고, 프롬프트는 서버와 같은
`build_*` 빌더로 렌더한다. 방 히스토리는 서버처럼 첫 메시지(스토리는 시작설정 첫 메시지, 캐릭터는 인트로)부터 쌓는다.

장면 파일의 대화는 줄 단위로 적는다 — 진행자 응답은 문단 목록과 상태창 네 칸(`status`)으로, 이 모듈이 시드 작품 규칙의
상태창(코드 블록 네 줄) 모양으로 잇는다. 스토리 칸은 시드에 미디어 북이 없어 장면 파일이 칸을 정의하고, 칸 id 는 칸
이름에서 결정적으로 파생한다.
"""

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from seed_content.ids import seed_uuid
from seed_content.loader import DATA_DIR, load_character, load_story

from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    MediaCellCandidate,
    StatJudgmentResult,
    build_ending_judgment_prompt,
    build_image_judgment_prompt,
    build_stat_judgment_prompt,
    media_cell_image_lines,
    situational_image_lines,
)
from api.content.publish import (
    PublishFilterResult,
    build_character_publish_filter_prompt,
    build_story_publish_filter_prompt,
)
from api.content.schemas import CharacterDraftPayload, StoryDraftPayload
from api.db.models.character import SituationalImage
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.story import StartingSetup, StatDef
from api.llm.client import LLMCallSite

from .prompts import PromptSnapshot

DATA_PATH = Path(__file__).parent / "data" / "tutorial_filmclub.json"

JudgmentKind = Literal["stat", "image", "ending", "publish"]
KINDS: tuple[JudgmentKind, ...] = ("stat", "image", "ending", "publish")


@dataclass(frozen=True)
class ReplayInput:
    input_id: str
    kind: JudgmentKind
    call_site: LLMCallSite
    prompt: str
    schema: type[BaseModel]
    image_paths: list[Path]
    # 판정 결과와 비교할 설계 정답(JSON 으로 남길 수 있는 값). 스탯은 {스탯 이름: "+"|"-"|"0"}, 그림은 후보 이름 또는
    # None, 엔딩은 발동 여부, 발행 심사는 통과 여부.
    expected: Any
    # 응답을 서버와 같은 후처리로 해석하는 데 필요한 것(`runner.derive`) + JSONL 에 남길 `meta`.
    context: dict[str, Any] = field(default_factory=dict)


def assistant_text(turn: dict[str, Any]) -> str:
    body = "\n\n".join(turn["assistant"])
    status = turn.get("status")
    if status is None:
        return str(body)
    place, time, present, now = status
    return f"{body}\n\n```\n장소 | {place}\n시간 | {time}\n함께 | {present}\n지금 | {now}\n```"


def media_cell_id(story_slug: str, key: str) -> uuid.UUID:
    """설계 칸의 id — 칸 이름에서 결정적으로 파생해 회차·실행이 달라도 같은 칸이 같은 id 를 갖는다."""
    return seed_uuid("judgment-replay", story_slug, "media-cell", key)


def _turns(raw: dict[str, Any], spec: list[list[Any]]) -> list[dict[str, Any]]:
    return [raw["logs"][name][index] for name, start, end in spec for index in range(start, end)]


def _history(opening: str, past: list[dict[str, Any]]) -> list[ChatMessage]:
    history = [ChatMessage(role=ChatMessageRole.ASSISTANT, content=opening)]
    for turn in past:
        history.append(ChatMessage(role=ChatMessageRole.USER, content=turn["user"]))
        history.append(ChatMessage(role=ChatMessageRole.ASSISTANT, content=assistant_text(turn)))
    return history


def _stat_defs(payload: StoryDraftPayload, setup_index: int) -> list[StatDef]:
    return [
        StatDef(
            entity_id=item.id,
            name=item.name,
            icon=item.icon,
            color=item.color,
            min_value=item.min_value,
            max_value=item.max_value,
            initial_value=item.initial_value,
            unit=item.unit,
            description=item.description,
            per_turn_delta=item.per_turn_delta,
            order=order,
        )
        for order, item in enumerate(payload.starting_setups[setup_index].stat_defs)
    ]


def _apply_overrides(payload: BaseModel, overrides: dict[str, Any]) -> Any:
    """거부 기대 사례용 변형 — 시드 글에 덧붙이거나 바꾼다. 키는 시드 JSON 과 같은 camelCase."""
    data = payload.model_dump(by_alias=True, mode="json")
    for key, value in overrides.get("replace", {}).items():
        data[key] = value
    for key, value in overrides.get("append", {}).items():
        data[key] = f"{data[key]}\n\n{value}" if data.get(key) else value
    for key, items in overrides.get("extend", {}).items():
        # 시드 로더처럼 덧붙인 항목에도 결정적 id 를 채운다(초안 스키마가 항목 id 를 요구한다).
        added = [
            {"id": str(seed_uuid("judgment-replay", key, str(len(data[key]) + i))), **item}
            for i, item in enumerate(items)
        ]
        data[key] = [*data[key], *added]
    return type(payload).model_validate(data)


def build_inputs(snapshot: PromptSnapshot, *, images_dir: Path, data_path: Path = DATA_PATH) -> list[ReplayInput]:
    raw: dict[str, Any] = json.loads(data_path.read_text(encoding="utf-8"))
    story_slug = Path(raw["story"]["seed"]).stem
    setup_index: int = raw["story"]["setup_index"]
    story = load_story(DATA_DIR / raw["story"]["seed"])
    character = load_character(DATA_DIR / raw["character"]["seed"])
    setup = story.starting_setups[setup_index]
    story_opening = setup.opening_message or setup.prologue

    story_set, story_sections = snapshot.lane("story")
    character_set, character_sections = snapshot.lane("character")
    filter_set, filter_sections = snapshot.lane("publish_filter")

    inputs: list[ReplayInput] = []

    # 스탯 — 이번 턴 한 쌍과 현재값만 싣는다(서버와 같다).
    stat_defs = _stat_defs(story, setup_index)
    stat_by_name = {stat_def.name: stat_def for stat_def in stat_defs}
    for case in raw["stat_cases"]:
        log, index = case["turn"]
        turn = raw["logs"][log][index]
        current = {str(stat_by_name[name].entity_id): float(value) for name, value in case["current"].items()}
        prompt = build_stat_judgment_prompt(
            prompt_set=story_set,
            sections=story_sections,
            stat_defs=stat_defs,
            current_stats=current,
            user_message=turn["user"],
            assistant_message=assistant_text(turn),
        )
        inputs.append(
            ReplayInput(
                input_id=case["id"],
                kind="stat",
                call_site="chat_stat_judgment",
                prompt=prompt,
                schema=StatJudgmentResult,
                image_paths=[],
                expected=case["expected"],
                context={"stat_defs": stat_defs, "current": current, "meta": {"source": f"{log}[{index}]"}},
            )
        )

    # 그림 — 캐릭터 상황 이미지(빌더 순서 = 우선순위)와 설계한 스토리 칸.
    situational = [
        SituationalImage(entity_id=item.id, trigger_condition=item.trigger_condition, order=order)
        for order, item in enumerate(character.situational_images)
    ]
    situational_labels = {str(image.entity_id): f"상황 이미지 {image.order + 1}" for image in situational}
    cells = [
        MediaCellCandidate(
            entity_id=media_cell_id(story_slug, cell["key"]),
            person=cell["person"],
            scene=cell["scene"],
            situation_description=cell["situation"],
        )
        for cell in raw["story_media_cells"]
    ]
    cell_labels = {str(cell.entity_id): f"{cell.person}/{cell.scene}" for cell in cells}
    for case in raw["image_cases"]:
        turns = _turns(raw, case["turns"])
        labels: dict[str, str]
        image_call_site: LLMCallSite
        if case["target"] == "character":
            prompt = build_image_judgment_prompt(
                prompt_set=character_set,
                sections=character_sections,
                scope="character",
                assistant_label=character_set.character_assistant_label,
                image_lines=situational_image_lines(situational),
                history=_history(character.intro, turns[:-1]),
                user_message=turns[-1]["user"],
                assistant_message=assistant_text(turns[-1]),
            )
            labels, image_call_site = situational_labels, "chat_situational_image"
        else:
            prompt = build_image_judgment_prompt(
                prompt_set=story_set,
                sections=story_sections,
                scope="story",
                assistant_label=story_set.story_assistant_label,
                image_lines=media_cell_image_lines(cells),
                history=_history(story_opening, turns[:-1]),
                user_message=turns[-1]["user"],
                assistant_message=assistant_text(turns[-1]),
            )
            labels, image_call_site = cell_labels, "chat_media_book_image"
        inputs.append(
            ReplayInput(
                input_id=case["id"],
                kind="image",
                call_site=image_call_site,
                prompt=prompt,
                schema=ImageMatchJudgmentResult,
                image_paths=[],
                expected=case["expected"],
                context={"candidates": labels, "meta": {"target": case["target"], "turn_count": len(turns)}},
            )
        )

    # 엔딩 — 엔딩 하나의 판정 문구 + 히스토리 전체(요약 없음, 서버 기본값과 같다).
    endings = {ending.name: ending for ending in setup.endings}
    for case in raw["ending_cases"]:
        turns = _turns(raw, case["turns"])
        prompt = build_ending_judgment_prompt(
            prompt_set=story_set,
            sections=story_sections,
            judgment_prompt=endings[case["ending"]].judgment_prompt,
            history=_history(story_opening, turns[:-1]),
            user_message=turns[-1]["user"],
            assistant_message=assistant_text(turns[-1]),
            memory_summary="",
        )
        inputs.append(
            ReplayInput(
                input_id=case["id"],
                kind="ending",
                call_site="chat_ending_judgment",
                prompt=prompt,
                schema=EndingJudgmentResult,
                image_paths=[],
                expected=case["expected"],
                context={"meta": {"ending": case["ending"], "turn_count": len(turns)}},
            )
        )

    # 발행 심사 — 시드 글 그대로(통과 기대)와 정책 위반을 덧붙인 변형(거부 기대). 이미지는 장면 파일이 고른 시드 그림.
    for case in raw["publish_cases"]:
        image_paths = [images_dir / name for name in case["images"]]
        if case["target"] == "story":
            variant: StoryDraftPayload = _apply_overrides(story, case["overrides"])
            prompt = build_story_publish_filter_prompt(
                prompt_set=filter_set,
                sections=filter_sections,
                name=variant.name,
                one_liner=variant.one_liner,
                setting_text=variant.setting_text,
                development_example=variant.development_example,
                custom_prompt=variant.custom_prompt,
                development_examples=[item.model_dump(by_alias=True) for item in variant.development_examples],
                user_goal=variant.user_goal,
                rules=variant.rules,
                detail_description=variant.description,
                starting_setups=[
                    StartingSetup(name=item.name, prologue=item.prologue) for item in variant.starting_setups
                ],
                media_cells=[],
            )
            publish_call_site: LLMCallSite = "publish_filter_story"
        else:
            character_variant: CharacterDraftPayload = _apply_overrides(character, case["overrides"])
            prompt = build_character_publish_filter_prompt(
                prompt_set=filter_set,
                sections=filter_sections,
                name=character_variant.name,
                one_liner=character_variant.one_liner,
                intro=character_variant.intro,
                example_dialogues=[item.model_dump(by_alias=True) for item in character_variant.example_dialogues],
                character_prompt=character_variant.character_prompt,
                detail_description=character_variant.description,
            )
            publish_call_site = "publish_filter_character"
        inputs.append(
            ReplayInput(
                input_id=case["id"],
                kind="publish",
                call_site=publish_call_site,
                prompt=prompt,
                schema=PublishFilterResult,
                image_paths=image_paths,
                expected=case["expected"],
                context={"meta": {"target": case["target"], "images": case["images"]}},
            )
        )
    return inputs
