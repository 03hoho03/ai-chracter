"""프롬프트 DB 이관 직전에 이관 전 코드가 실제로 내는 프롬프트 전문을 골든 파일로 뜬 스크립트.

여기서 만든 파일들(`tests/golden/prompts/*.txt`)은 이관 전후 바이트 동일을 증명하는
기준선이다. `tests/test_prompt_goldens.py`가 아래 `GOLDEN_CASES`를 그대로
재사용해 지금 렌더러의 출력과 골든 파일을 대조한다 — 픽스처가 두 곳에서 갈리면 그
대조는 무의미해지므로 이 모듈이 픽스처의 유일한 정의처다("자기 사본 함정" 방지,
`25a6ae1`이 겪은 것과 같은 종류의 실수를 물리적으로 막는다).

**렌더러를 DB 기반으로 교체한 뒤로는 `main()`이 더 이상 DB 없이 못 돈다.** `build_*` 함수들이
`PromptSet`/`PromptSection`을 받게 바뀌어서, 이 스크립트도 활성 세트를 DB에서 읽어야
호출할 수 있다. `GOLDEN_CASES`의 각 콜러블 자체는 여전히 `(prompt_set, sections)`를
받는 순수 함수 호출일 뿐이라 import 시점에는 DB가 필요 없다 — DB가 필요한 것은
`main()`을 실제로 실행할 때뿐이다.

⚠️ **`main()`을 다시 실행해 골든 파일을 덮어쓰지 마라.** 골든은 이관 *전* 코드가 낸
문자열을 영구 보존한 기준선이다 — 지금 렌더러로 다시 뜨면 렌더러의 버그까지
"정답"으로 덮어써 버려 이 대조가 원리적으로 무력화된다. 이 파일이 남아 있는 이유는
오직 `GOLDEN_CASES`/픽스처 리터럴을 테스트와 공유하기 위해서다.

실행(위 경고를 무릅쓰고 재현 검증 등으로 정말 필요할 때만):
    cd apps/api && uv run python scripts/dump_prompt_goldens.py
"""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_args
from uuid import UUID

from api.chat.prompt_builder import (
    MediaCellCandidate,
    PromptLane,
    build_ending_judgment_prompt,
    build_generation_prompt,
    build_image_judgment_prompt,
    build_stat_judgment_prompt,
    build_story_generation_prompt,
    load_active_prompt_set,
    media_cell_image_lines,
    situational_image_lines,
    system_instruction_for,
)
from api.content.publish import (
    MediaBookFilterCell,
    build_character_publish_filter_prompt,
    build_story_publish_filter_prompt,
)
from api.db.models.character import SituationalImage
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import StatDef, StoryPromptTemplate
from api.db.session import async_session_factory

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "tests" / "golden" / "prompts"


# ---- 공용 픽스처 조각 -------------------------------------------------------
#
# 대화 기록/스탯/이미지의 entity_id는 골든 파일 본문에 그대로 찍히므로 uuid4()가 아니라
# 고정 리터럴을 쓴다 — 안 그러면 스크립트를 다시 돌릴 때마다 골든이 바뀐다.

_AFFECTION_ENTITY_ID = UUID("11111111-1111-1111-1111-111111111111")
_STAMINA_ENTITY_ID = UUID("22222222-2222-2222-2222-222222222222")
_IMAGE_ENTITY_ID_SMILE = UUID("33333333-3333-3333-3333-333333333333")
_IMAGE_ENTITY_ID_ANGRY = UUID("44444444-4444-4444-4444-444444444444")
_MEDIA_CELL_ENTITY_ID_ROOFTOP = UUID("55555555-5555-5555-5555-555555555555")
_MEDIA_CELL_ENTITY_ID_CLASSROOM = UUID("66666666-6666-6666-6666-666666666666")

CHARACTER_PROMPT = "너는 밤늦게 옥상에서 마주친 낯선 사람이다. 말수는 적지만 관찰력이 좋다."

STORY_SETTING_TEXT = "낡은 아파트 옥상. 화자는 3인칭으로 장면을 서술하며 인물의 속마음은 직접 말하지 않는다."
STORY_CUSTOM_PROMPT = "당신은 이 이야기의 진행자다. 매 턴 옥상의 날씨를 한 줄로 묘사한 뒤 장면을 이어간다."
STORY_RULES = "인물은 절대 사용자의 이름을 먼저 부르지 않는다."
STORY_USER_GOAL = "사용자는 떠난 친구가 옥상에 남긴 마지막 메모를 찾아야 한다."
STORY_PROLOGUE = "옥상 문은 살짝 열려 있다. 바람에 종잇조각 하나가 팔랑인다."

KEYWORD_NOTE_TEXT = "종잇조각: 친구가 옥상에서 마지막으로 쓴 메모. 젖어서 글씨가 반쯤 지워졌다."
SHORTCUT_PROMPT = "[단축어: 주변 둘러보기] 사용자가 옥상 구석구석을 살펴본다."

USER_MESSAGE = "괜찮아? 표정이 안 좋아 보여."
ASSISTANT_MESSAGE = "…아니, 괜찮아. 그냥 바람 좀 쐬고 싶었을 뿐이야."

ENDING_JUDGMENT_PROMPT = "사용자가 종잇조각의 내용을 완전히 읽어내고 그 의미를 인물에게 직접 말했다면 이 엔딩이 발동한다."

EXAMPLE_DIALOGUE: dict[str, Any] = {"userLine": "거기서 뭐 해?", "characterLine": "그냥, 별 보고 있었어."}
DEVELOPMENT_EXAMPLE: dict[str, Any] = {
    "userLine": "문을 두드려 본다.",
    "assistantLine": "안에서는 아무 대답도 들리지 않는다. 손잡이가 잠겨 있다.",
}


# 미디어 북 이미지 태그가 든 프롤로그·대화 기록. 태그는 화면에서만 이미지가 되고 모델로 가는 사본에서는
# 지워져야 한다 — 빈 줄 사이에 홀로 선 태그 줄은 빈 줄 하나로 접히고, 글 맨 앞 태그 줄은 사라지고, 줄 중간
# 태그는 글자만 사라진다. 미디어 북 태그가 아닌 `{{user}}` 는 그대로 남는다.
STORY_PROLOGUE_WITH_MEDIA_TAGS = "옥상 문은 살짝 열려 있다.\n\n{{img::민아/옥상}}\n\n바람에 종잇조각 하나가 팔랑인다."
# 태그 없이 빈 줄이 연달아 있는 글. 태그를 지우며 생긴 빈 줄만 접어야 하므로 이 글은 그대로 나가야 한다.
STORY_PROLOGUE_WITH_BLANK_LINES = "옥상 문은 살짝 열려 있다.\n\n\n바람에 종잇조각 하나가 팔랑인다."


def _story_history_with_media_tags() -> list[ChatMessage]:
    return [
        ChatMessage(
            role=ChatMessageRole.ASSISTANT,
            content="{{img::55555555-5555-5555-5555-555555555555}}\n옥상 문은 살짝 열려 있다. {{img::민아/옥상}}바람이 분다.",
        ),
        ChatMessage(role=ChatMessageRole.USER, content="{{user}}는 문을 두드려 본다."),
    ]


def _story_history_with_blank_lines() -> list[ChatMessage]:
    return [ChatMessage(role=ChatMessageRole.ASSISTANT, content="안에서는 인기척이 없다.\n\n\n발소리만 멀어진다.")]


def _character_history() -> list[ChatMessage]:
    return [
        ChatMessage(role=ChatMessageRole.USER, content="거기 누구 있어요?"),
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="…나야. 놀랐다면 미안."),
    ]


def _story_history() -> list[ChatMessage]:
    return [
        ChatMessage(role=ChatMessageRole.USER, content="문을 두드려 본다."),
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="안에서는 인기척이 없다."),
    ]


def _stat_defs() -> list[StatDef]:
    return [
        StatDef(
            entity_id=_AFFECTION_ENTITY_ID,
            name="호감도",
            description="호감도가 오르면 더 다정해진다.",
            min_value=0,
            max_value=100,
            initial_value=50,
            per_turn_delta=None,
        ),
        # per_turn_delta가 있는 스탯은 current_stats에 값을 안 넣어 initial_value 폴백과
        # "시스템이 매 턴 자동 조정" 문구가 동시에 골든에 찍히게 한다.
        StatDef(
            entity_id=_STAMINA_ENTITY_ID,
            name="체력",
            description="체력이 다하면 대화를 이어가기 힘들어진다.",
            min_value=0,
            max_value=100,
            initial_value=100,
            per_turn_delta=-5,
        ),
    ]


def _situational_images() -> list[SituationalImage]:
    return [
        SituationalImage(entity_id=_IMAGE_ENTITY_ID_SMILE, trigger_condition="캐릭터가 웃을 때", order=0),
        SituationalImage(entity_id=_IMAGE_ENTITY_ID_ANGRY, trigger_condition="캐릭터가 화낼 때", order=1),
    ]


def _media_cells() -> list[MediaCellCandidate]:
    return [
        MediaCellCandidate(
            entity_id=_MEDIA_CELL_ENTITY_ID_ROOFTOP, person="민아", scene="옥상", situation_description="난간에 기대 웃는다"
        ),
        MediaCellCandidate(entity_id=_MEDIA_CELL_ENTITY_ID_CLASSROOM, person="민아", scene="교실", situation_description=""),
    ]


def _media_book_filter_cells() -> list[MediaBookFilterCell]:
    """발행 심사 이미지 목록의 칸 라벨 — 축 순서(인물 → 장면)로 이미 정렬된 칸 셋."""
    return [
        MediaBookFilterCell(person="민아", scene="옥상"),
        MediaBookFilterCell(person="민아", scene="교실"),
        MediaBookFilterCell(person="준", scene="교실"),
    ]


# ---- 골든 케이스 ------------------------------------------------------------
#
# (파일명, 레인, (prompt_set, sections) -> 프롬프트 문자열인 콜러블) 3-튜플의 목록.
# `build_*`가 `PromptSet`/`PromptSection` 목록을 받으므로 콜러블도 그 둘을 인자로 받는다 —
# `tests/test_prompt_goldens.py`가 이 목록을 그대로 import해서, 레인별로 DB에서 읽은
# 활성 세트를 넘겨 각 콜러블의 실행 결과를 같은 이름의 골든 파일과 비교한다. 레인 배정은
# 채널→레인 매핑 그대로다 — system/generation은
# scope(캐릭터/스토리)로, stat_judgment·ending_judgment는 story로, image_judgment는
# character로(스토리 미디어 북 칸 판정만 story), publish_filter는 publish_filter로 고정.

GoldenBuilder = Callable[[PromptSet, list[PromptSection]], str]

GOLDEN_CASES: list[tuple[str, PromptLane, GoldenBuilder]] = [
    # -- system_instruction: 캐릭터 / 스토리×템플릿 4종 / 스토리-무템플릿 = 6 --
    (
        "system_instruction_character.txt",
        "character",
        lambda ps, sections: system_instruction_for(sections, is_story_chat=False),
    ),
    (
        "system_instruction_story_basic.txt",
        "story",
        lambda ps, sections: system_instruction_for(
            sections, is_story_chat=True, template=StoryPromptTemplate.BASIC
        ),
    ),
    (
        "system_instruction_story_emotional.txt",
        "story",
        lambda ps, sections: system_instruction_for(
            sections, is_story_chat=True, template=StoryPromptTemplate.EMOTIONAL
        ),
    ),
    (
        "system_instruction_story_simulation.txt",
        "story",
        lambda ps, sections: system_instruction_for(
            sections, is_story_chat=True, template=StoryPromptTemplate.SIMULATION
        ),
    ),
    (
        "system_instruction_story_custom.txt",
        "story",
        lambda ps, sections: system_instruction_for(
            sections, is_story_chat=True, template=StoryPromptTemplate.CUSTOM
        ),
    ),
    (
        "system_instruction_story_no_template.txt",
        "story",
        lambda ps, sections: system_instruction_for(sections, is_story_chat=True, template=None),
    ),
    # 생성 7건은 `user_persona=""`(프로필 없음·선택 없음)이고 기억(`memory_note`·`memory_summary`)도
    # 빈 값이다(엔딩 2건의 `memory_summary`도) — 이 인자들이 없던 시절의 골든과 바이트까지 같아야
    # 한다(골든은 다시 뜨지 않는다).
    # -- 생성 프롬프트: 캐릭터 1 × filled/empty + 경계(character_prompt="") --
    (
        "generation_character_filled.txt",
        "character",
        lambda ps, sections: build_generation_prompt(
            prompt_set=ps,
            sections=sections,
            character_prompt=CHARACTER_PROMPT,
            example_dialogues=[EXAMPLE_DIALOGUE],
            history=_character_history(),
            user_message=USER_MESSAGE,
            user_persona="",
            memory_note="",
            memory_summary="",
        ),
    ),
    (
        "generation_character_empty.txt",
        "character",
        lambda ps, sections: build_generation_prompt(
            prompt_set=ps,
            sections=sections,
            character_prompt=CHARACTER_PROMPT,
            example_dialogues=[],
            history=[],
            user_message=USER_MESSAGE,
            user_persona="",
            memory_note="",
            memory_summary="",
        ),
    ),
    (
        "generation_character_empty_prompt.txt",
        "character",
        lambda ps, sections: build_generation_prompt(
            prompt_set=ps,
            sections=sections,
            character_prompt="",
            example_dialogues=[EXAMPLE_DIALOGUE],
            history=_character_history(),
            user_message=USER_MESSAGE,
            user_persona="",
            memory_note="",
            memory_summary="",
        ),
    ),
    # -- 생성 프롬프트: 스토리 CUSTOM/비-CUSTOM(BASIC 대표) × filled/empty --
    (
        "generation_story_custom_filled.txt",
        "story",
        lambda ps, sections: build_story_generation_prompt(
            prompt_set=ps,
            sections=sections,
            prompt_template=StoryPromptTemplate.CUSTOM,
            setting_text=None,
            development_examples=[DEVELOPMENT_EXAMPLE],
            user_goal=STORY_USER_GOAL,
            rules=STORY_RULES,
            custom_prompt=STORY_CUSTOM_PROMPT,
            prologue=STORY_PROLOGUE,
            history=_story_history(),
            user_message=USER_MESSAGE,
            user_persona="",
            memory_note="",
            memory_summary="",
            keyword_note_texts=[KEYWORD_NOTE_TEXT],
            shortcut_prompt=SHORTCUT_PROMPT,
        ),
    ),
    (
        "generation_story_custom_empty.txt",
        "story",
        lambda ps, sections: build_story_generation_prompt(
            prompt_set=ps,
            sections=sections,
            prompt_template=StoryPromptTemplate.CUSTOM,
            setting_text=None,
            development_examples=[],
            user_goal=None,
            rules=None,
            custom_prompt=None,
            prologue=STORY_PROLOGUE,
            history=[],
            user_message=USER_MESSAGE,
            user_persona="",
            memory_note="",
            memory_summary="",
            keyword_note_texts=None,
            shortcut_prompt=None,
        ),
    ),
    (
        "generation_story_basic_filled.txt",
        "story",
        lambda ps, sections: build_story_generation_prompt(
            prompt_set=ps,
            sections=sections,
            prompt_template=StoryPromptTemplate.BASIC,
            setting_text=STORY_SETTING_TEXT,
            development_examples=[DEVELOPMENT_EXAMPLE],
            user_goal=STORY_USER_GOAL,
            rules=STORY_RULES,
            custom_prompt=None,
            prologue=STORY_PROLOGUE,
            history=_story_history(),
            user_message=USER_MESSAGE,
            user_persona="",
            memory_note="",
            memory_summary="",
            keyword_note_texts=[KEYWORD_NOTE_TEXT],
            shortcut_prompt=SHORTCUT_PROMPT,
        ),
    ),
    (
        "generation_story_basic_empty.txt",
        "story",
        lambda ps, sections: build_story_generation_prompt(
            prompt_set=ps,
            sections=sections,
            prompt_template=StoryPromptTemplate.BASIC,
            setting_text=None,
            development_examples=[],
            user_goal=None,
            rules=None,
            custom_prompt=None,
            prologue=STORY_PROLOGUE,
            history=[],
            user_message=USER_MESSAGE,
            user_persona="",
            memory_note="",
            memory_summary="",
            keyword_note_texts=None,
            shortcut_prompt=None,
        ),
    ),
    # -- 생성 프롬프트: 미디어 북 태그 제거 --
    # 아래 두 파일은 이관 전 코드에서 뜬 것이 아니라 기대 텍스트를 손으로 적은 것이다(이관 전에는 태그
    # 제거가 없었다). 그래서 `main()` 으로 다시 뜨면 안 되는 이유가 하나 더 생긴다 — 렌더러가 내는 값을
    # 정답으로 덮으면 손으로 적은 기대가 사라진다.
    (
        "generation_story_basic_media_tags.txt",
        "story",
        lambda ps, sections: build_story_generation_prompt(
            prompt_set=ps,
            sections=sections,
            prompt_template=StoryPromptTemplate.BASIC,
            setting_text=None,
            development_examples=[],
            user_goal=None,
            rules=None,
            custom_prompt=None,
            prologue=STORY_PROLOGUE_WITH_MEDIA_TAGS,
            history=_story_history_with_media_tags(),
            user_message=USER_MESSAGE,
            user_persona="",
            memory_note="",
            memory_summary="",
            keyword_note_texts=None,
            shortcut_prompt=None,
        ),
    ),
    (
        "generation_story_basic_blank_lines.txt",
        "story",
        lambda ps, sections: build_story_generation_prompt(
            prompt_set=ps,
            sections=sections,
            prompt_template=StoryPromptTemplate.BASIC,
            setting_text=None,
            development_examples=[],
            user_goal=None,
            rules=None,
            custom_prompt=None,
            prologue=STORY_PROLOGUE_WITH_BLANK_LINES,
            history=_story_history_with_blank_lines(),
            user_message=USER_MESSAGE,
            user_persona="",
            memory_note="",
            memory_summary="",
            keyword_note_texts=None,
            shortcut_prompt=None,
        ),
    ),
    # -- 판단 프롬프트: 스탯/엔딩/이미지 × filled/empty --
    (
        "judgment_stat_filled.txt",
        "story",
        lambda ps, sections: build_stat_judgment_prompt(
            prompt_set=ps,
            sections=sections,
            stat_defs=_stat_defs(),
            current_stats={str(_AFFECTION_ENTITY_ID): 62.0},
            user_message=USER_MESSAGE,
            assistant_message=ASSISTANT_MESSAGE,
        ),
    ),
    (
        "judgment_stat_empty.txt",
        "story",
        lambda ps, sections: build_stat_judgment_prompt(
            prompt_set=ps,
            sections=sections,
            stat_defs=[],
            current_stats={},
            user_message=USER_MESSAGE,
            assistant_message=ASSISTANT_MESSAGE,
        ),
    ),
    (
        "judgment_ending_filled.txt",
        "story",
        lambda ps, sections: build_ending_judgment_prompt(
            prompt_set=ps,
            sections=sections,
            judgment_prompt=ENDING_JUDGMENT_PROMPT,
            history=_story_history(),
            user_message=USER_MESSAGE,
            assistant_message=ASSISTANT_MESSAGE,
            memory_summary="",
        ),
    ),
    (
        "judgment_ending_empty.txt",
        "story",
        lambda ps, sections: build_ending_judgment_prompt(
            prompt_set=ps,
            sections=sections,
            judgment_prompt=ENDING_JUDGMENT_PROMPT,
            history=[],
            user_message=USER_MESSAGE,
            assistant_message=ASSISTANT_MESSAGE,
            memory_summary="",
        ),
    ),
    (
        "judgment_image_filled.txt",
        "character",
        lambda ps, sections: build_image_judgment_prompt(
            prompt_set=ps,
            sections=sections,
            scope="character",
            assistant_label=ps.character_assistant_label,
            image_lines=situational_image_lines(_situational_images()),
            history=_character_history(),
            user_message=USER_MESSAGE,
            assistant_message=ASSISTANT_MESSAGE,
        ),
    ),
    (
        "judgment_image_empty.txt",
        "character",
        lambda ps, sections: build_image_judgment_prompt(
            prompt_set=ps,
            sections=sections,
            scope="character",
            assistant_label=ps.character_assistant_label,
            image_lines=situational_image_lines([]),
            history=[],
            user_message=USER_MESSAGE,
            assistant_message=ASSISTANT_MESSAGE,
        ),
    ),
    # 스토리 미디어 북 칸 판정 — 위 캐릭터 골든을 뜬 뒤에 더한 케이스라 기대 텍스트를 손으로 적었다.
    # 상황 설명이 있는 칸과 없는 칸, 칸 id 형태·이름 형태 태그가 든 대화 기록(판정에는 실리지 않는다).
    (
        "judgment_media_cell_filled.txt",
        "story",
        lambda ps, sections: build_image_judgment_prompt(
            prompt_set=ps,
            sections=sections,
            scope="story",
            assistant_label=ps.story_assistant_label,
            image_lines=media_cell_image_lines(_media_cells()),
            history=_story_history_with_media_tags(),
            user_message=USER_MESSAGE,
            assistant_message=ASSISTANT_MESSAGE,
        ),
    ),
    # -- 발행 심사: 이미지 목록만 싣는다 --
    # 발행 심사를 이미지 전용으로 바꾼 뒤에 다시 적은 케이스라 기대 텍스트를 손으로 적었다. 작가 글이 프롬프트에
    # 실리지 않으므로 이미지 수와 칸 이름만 입력이다.
    (
        "publish_filter_character.txt",
        "publish_filter",
        lambda ps, sections: build_character_publish_filter_prompt(sections=sections, situational_image_count=2),
    ),
    (
        "publish_filter_story.txt",
        "publish_filter",
        lambda ps, sections: build_story_publish_filter_prompt(sections=sections, media_cells=[]),
    ),
    (
        "publish_filter_story_media_book.txt",
        "publish_filter",
        lambda ps, sections: build_story_publish_filter_prompt(sections=sections, media_cells=_media_book_filter_cells()),
    ),
]


async def _load_active_prompt_sets() -> dict[PromptLane, tuple[PromptSet, list[PromptSection]]]:
    async with async_session_factory() as session:
        return {
            lane: await load_active_prompt_set(session, lane=lane) for lane in get_args(PromptLane)
        }


def main() -> None:
    prompt_sets_by_lane = asyncio.run(_load_active_prompt_sets())
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for filename, lane, build in GOLDEN_CASES:
        prompt_set, sections = prompt_sets_by_lane[lane]
        (GOLDEN_DIR / filename).write_text(build(prompt_set, sections), encoding="utf-8")
    print(f"{len(GOLDEN_CASES)}개 골든 파일을 {GOLDEN_DIR}에 썼다.")


if __name__ == "__main__":
    main()
