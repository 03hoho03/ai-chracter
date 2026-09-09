"""프롬프트 DB 이관 0단계 — 이관 전 코드가 실제로 내는 프롬프트 전문을 골든 파일로 뜬다.

여기서 만드는 파일들은 나중 단계에서 렌더러를 갈아엎은 뒤 바이트 단위로 비교해 "품질이
안 변했다"를 증명하는 기준선이다. `tests/test_prompt_goldens.py`가 아래 `GOLDEN_CASES`를
그대로 재사용해 지금 코드의 출력과 골든 파일을 대조한다 — 픽스처가 두 곳에서 갈리면 그
대조는 무의미해지므로 이 모듈이 픽스처의 유일한 정의처다.

DB·네트워크·LLM을 쓰지 않는다. 대상 함수는 전부 순수 함수이고, ORM 모델은 DB 세션 없이
생성자로만 채운다(`nullable=False`는 DB 제약일 뿐이라 프롬프트 조립에 안 쓰는 필드는 생략).

실행:
    cd apps/api && uv run python scripts/dump_prompt_goldens.py
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from api.chat.prompt_builder import (
    build_ending_judgment_prompt,
    build_generation_prompt,
    build_image_judgment_prompt,
    build_stat_judgment_prompt,
    build_story_generation_prompt,
    system_instruction_for,
)
from api.content.publish import (
    build_character_publish_filter_prompt,
    build_story_publish_filter_prompt,
)
from api.db.models.character import SituationalImage
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.story import StartingSetup, StatDef, StoryPromptTemplate

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "tests" / "golden" / "prompts"


# ---- 공용 픽스처 조각 -------------------------------------------------------
#
# 대화 기록/스탯/이미지의 entity_id는 골든 파일 본문에 그대로 찍히므로 uuid4()가 아니라
# 고정 리터럴을 쓴다 — 안 그러면 스크립트를 다시 돌릴 때마다 골든이 바뀐다.

_AFFECTION_ENTITY_ID = UUID("11111111-1111-1111-1111-111111111111")
_STAMINA_ENTITY_ID = UUID("22222222-2222-2222-2222-222222222222")
_IMAGE_ENTITY_ID_SMILE = UUID("33333333-3333-3333-3333-333333333333")
_IMAGE_ENTITY_ID_ANGRY = UUID("44444444-4444-4444-4444-444444444444")

CHARACTER_PROMPT = "너는 밤늦게 옥상에서 마주친 낯선 사람이다. 말수는 적지만 관찰력이 좋다."
CHARACTER_NAME = "밤의 목격자"
CHARACTER_ONE_LINER = "이름도 모르는 밤의 목격자와 나누는 대화."
CHARACTER_INTRO = "옥상 난간에 기대 선 채로, 그가 담배 연기 사이로 너를 돌아본다."
CHARACTER_DETAIL_DESCRIPTION = "매일 자정 옥상에 올라오는 정체불명의 인물과 이야기를 나누는 캐릭터 챗입니다."

STORY_NAME = "옥상의 약속"
STORY_ONE_LINER = "떠난 사람이 남긴 옥상의 약속을 되짚는 이야기."
STORY_SETTING_TEXT = "낡은 아파트 옥상. 화자는 3인칭으로 장면을 서술하며 인물의 속마음은 직접 말하지 않는다."
STORY_CUSTOM_PROMPT = "당신은 이 이야기의 진행자다. 매 턴 옥상의 날씨를 한 줄로 묘사한 뒤 장면을 이어간다."
STORY_RULES = "인물은 절대 사용자의 이름을 먼저 부르지 않는다."
STORY_USER_GOAL = "사용자는 떠난 친구가 옥상에 남긴 마지막 메모를 찾아야 한다."
STORY_PROLOGUE = "옥상 문은 살짝 열려 있다. 바람에 종잇조각 하나가 팔랑인다."
STORY_DEVELOPMENT_EXAMPLE_TEXT = "사용자가 문을 두드리면, 안에서는 대답 대신 발소리만 들린다."
STORY_DETAIL_DESCRIPTION = "옥상에 남겨진 마지막 메모를 찾아가는 짧은 미스터리 스토리 챗입니다."

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


def _starting_setup() -> StartingSetup:
    return StartingSetup(name="첫 만남", prologue=STORY_PROLOGUE)


# ---- 골든 케이스 ------------------------------------------------------------
#
# (파일명, 인자 없이 프롬프트 문자열을 내는 콜러블) 쌍의 목록. `test_prompt_goldens.py`가
# 이 목록을 그대로 import해서 각 콜러블의 실행 결과를 같은 이름의 골든 파일과 비교한다.

GOLDEN_CASES: list[tuple[str, Callable[[], str]]] = [
    # -- system_instruction: 캐릭터 / 스토리×템플릿 4종 / 스토리-무템플릿 = 6 --
    (
        "system_instruction_character.txt",
        lambda: system_instruction_for(is_story_chat=False),
    ),
    (
        "system_instruction_story_basic.txt",
        lambda: system_instruction_for(is_story_chat=True, template=StoryPromptTemplate.BASIC),
    ),
    (
        "system_instruction_story_emotional.txt",
        lambda: system_instruction_for(is_story_chat=True, template=StoryPromptTemplate.EMOTIONAL),
    ),
    (
        "system_instruction_story_simulation.txt",
        lambda: system_instruction_for(is_story_chat=True, template=StoryPromptTemplate.SIMULATION),
    ),
    (
        "system_instruction_story_custom.txt",
        lambda: system_instruction_for(is_story_chat=True, template=StoryPromptTemplate.CUSTOM),
    ),
    (
        "system_instruction_story_no_template.txt",
        lambda: system_instruction_for(is_story_chat=True, template=None),
    ),
    # -- 생성 프롬프트: 캐릭터 1 × filled/empty + 경계(character_prompt="") --
    (
        "generation_character_filled.txt",
        lambda: build_generation_prompt(
            character_prompt=CHARACTER_PROMPT,
            example_dialogues=[EXAMPLE_DIALOGUE],
            history=_character_history(),
            user_message=USER_MESSAGE,
        ),
    ),
    (
        "generation_character_empty.txt",
        lambda: build_generation_prompt(
            character_prompt=CHARACTER_PROMPT,
            example_dialogues=[],
            history=[],
            user_message=USER_MESSAGE,
        ),
    ),
    (
        "generation_character_empty_prompt.txt",
        lambda: build_generation_prompt(
            character_prompt="",
            example_dialogues=[EXAMPLE_DIALOGUE],
            history=_character_history(),
            user_message=USER_MESSAGE,
        ),
    ),
    # -- 생성 프롬프트: 스토리 CUSTOM/비-CUSTOM(BASIC 대표) × filled/empty --
    (
        "generation_story_custom_filled.txt",
        lambda: build_story_generation_prompt(
            prompt_template=StoryPromptTemplate.CUSTOM,
            setting_text=None,
            development_examples=[DEVELOPMENT_EXAMPLE],
            user_goal=STORY_USER_GOAL,
            rules=STORY_RULES,
            custom_prompt=STORY_CUSTOM_PROMPT,
            prologue=STORY_PROLOGUE,
            history=_story_history(),
            user_message=USER_MESSAGE,
            keyword_note_texts=[KEYWORD_NOTE_TEXT],
            shortcut_prompt=SHORTCUT_PROMPT,
        ),
    ),
    (
        "generation_story_custom_empty.txt",
        lambda: build_story_generation_prompt(
            prompt_template=StoryPromptTemplate.CUSTOM,
            setting_text=None,
            development_examples=[],
            user_goal=None,
            rules=None,
            custom_prompt=None,
            prologue=STORY_PROLOGUE,
            history=[],
            user_message=USER_MESSAGE,
            keyword_note_texts=None,
            shortcut_prompt=None,
        ),
    ),
    (
        "generation_story_basic_filled.txt",
        lambda: build_story_generation_prompt(
            prompt_template=StoryPromptTemplate.BASIC,
            setting_text=STORY_SETTING_TEXT,
            development_examples=[DEVELOPMENT_EXAMPLE],
            user_goal=STORY_USER_GOAL,
            rules=STORY_RULES,
            custom_prompt=None,
            prologue=STORY_PROLOGUE,
            history=_story_history(),
            user_message=USER_MESSAGE,
            keyword_note_texts=[KEYWORD_NOTE_TEXT],
            shortcut_prompt=SHORTCUT_PROMPT,
        ),
    ),
    (
        "generation_story_basic_empty.txt",
        lambda: build_story_generation_prompt(
            prompt_template=StoryPromptTemplate.BASIC,
            setting_text=None,
            development_examples=[],
            user_goal=None,
            rules=None,
            custom_prompt=None,
            prologue=STORY_PROLOGUE,
            history=[],
            user_message=USER_MESSAGE,
            keyword_note_texts=None,
            shortcut_prompt=None,
        ),
    ),
    # -- 판단 프롬프트: 스탯/엔딩/이미지 × filled/empty --
    (
        "judgment_stat_filled.txt",
        lambda: build_stat_judgment_prompt(
            stat_defs=_stat_defs(),
            current_stats={str(_AFFECTION_ENTITY_ID): 62.0},
            user_message=USER_MESSAGE,
            assistant_message=ASSISTANT_MESSAGE,
        ),
    ),
    (
        "judgment_stat_empty.txt",
        lambda: build_stat_judgment_prompt(
            stat_defs=[],
            current_stats={},
            user_message=USER_MESSAGE,
            assistant_message=ASSISTANT_MESSAGE,
        ),
    ),
    (
        "judgment_ending_filled.txt",
        lambda: build_ending_judgment_prompt(
            judgment_prompt=ENDING_JUDGMENT_PROMPT,
            history=_story_history(),
            user_message=USER_MESSAGE,
            assistant_message=ASSISTANT_MESSAGE,
        ),
    ),
    (
        "judgment_ending_empty.txt",
        lambda: build_ending_judgment_prompt(
            judgment_prompt=ENDING_JUDGMENT_PROMPT,
            history=[],
            user_message=USER_MESSAGE,
            assistant_message=ASSISTANT_MESSAGE,
        ),
    ),
    (
        "judgment_image_filled.txt",
        lambda: build_image_judgment_prompt(
            situational_images=_situational_images(),
            history=_character_history(),
            user_message=USER_MESSAGE,
            assistant_message=ASSISTANT_MESSAGE,
        ),
    ),
    (
        "judgment_image_empty.txt",
        lambda: build_image_judgment_prompt(
            situational_images=[],
            history=[],
            user_message=USER_MESSAGE,
            assistant_message=ASSISTANT_MESSAGE,
        ),
    ),
    # -- 발행 검열: 캐릭터/스토리 × filled/empty --
    (
        "publish_filter_character_filled.txt",
        lambda: build_character_publish_filter_prompt(
            name=CHARACTER_NAME,
            one_liner=CHARACTER_ONE_LINER,
            intro=CHARACTER_INTRO,
            example_dialogues=[EXAMPLE_DIALOGUE],
            character_prompt=CHARACTER_PROMPT,
            detail_description=CHARACTER_DETAIL_DESCRIPTION,
        ),
    ),
    (
        "publish_filter_character_empty.txt",
        lambda: build_character_publish_filter_prompt(
            name=CHARACTER_NAME,
            one_liner=CHARACTER_ONE_LINER,
            intro=CHARACTER_INTRO,
            example_dialogues=[],
            character_prompt=CHARACTER_PROMPT,
            detail_description=CHARACTER_DETAIL_DESCRIPTION,
        ),
    ),
    (
        "publish_filter_story_filled.txt",
        lambda: build_story_publish_filter_prompt(
            name=STORY_NAME,
            one_liner=STORY_ONE_LINER,
            setting_text=STORY_SETTING_TEXT,
            development_example=STORY_DEVELOPMENT_EXAMPLE_TEXT,
            custom_prompt=STORY_CUSTOM_PROMPT,
            development_examples=[DEVELOPMENT_EXAMPLE],
            user_goal=STORY_USER_GOAL,
            rules=STORY_RULES,
            detail_description=STORY_DETAIL_DESCRIPTION,
            starting_setups=[_starting_setup()],
        ),
    ),
    (
        "publish_filter_story_empty.txt",
        lambda: build_story_publish_filter_prompt(
            name=STORY_NAME,
            one_liner=STORY_ONE_LINER,
            setting_text=None,
            development_example=None,
            custom_prompt=None,
            development_examples=[],
            user_goal=None,
            rules=None,
            detail_description=STORY_DETAIL_DESCRIPTION,
            starting_setups=[],
        ),
    ),
    # `development_example`(단수 레거시)과 `development_examples`(복수 신규)는 대각선
    # (둘 다 참/둘 다 거짓)만으로는 부족하다 — router.py의 `_update_story_draft`가
    # `development_example`은 payload에 명시된 경우에만 갱신하고(FE가 더 이상 안 보내는
    # 필드라 사실상 기존 값이 그대로 남는다) `development_examples`는 매번 통째로 덮어쓰므로,
    # "쌍 목록만 채워짐"이 신규 스토리의 기본 상태이자 "레거시 텍스트만 남고 쌍 목록은
    # 비워짐"도 사용자가 쌍을 전부 지우면 그대로 도달한다.
    (
        "publish_filter_story_pairs_only.txt",
        lambda: build_story_publish_filter_prompt(
            name=STORY_NAME,
            one_liner=STORY_ONE_LINER,
            setting_text=STORY_SETTING_TEXT,
            development_example=None,
            custom_prompt=STORY_CUSTOM_PROMPT,
            development_examples=[DEVELOPMENT_EXAMPLE],
            user_goal=STORY_USER_GOAL,
            rules=STORY_RULES,
            detail_description=STORY_DETAIL_DESCRIPTION,
            starting_setups=[_starting_setup()],
        ),
    ),
    (
        "publish_filter_story_legacy_only.txt",
        lambda: build_story_publish_filter_prompt(
            name=STORY_NAME,
            one_liner=STORY_ONE_LINER,
            setting_text=STORY_SETTING_TEXT,
            development_example=STORY_DEVELOPMENT_EXAMPLE_TEXT,
            custom_prompt=STORY_CUSTOM_PROMPT,
            development_examples=[],
            user_goal=STORY_USER_GOAL,
            rules=STORY_RULES,
            detail_description=STORY_DETAIL_DESCRIPTION,
            starting_setups=[_starting_setup()],
        ),
    ),
]


def main() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for filename, build in GOLDEN_CASES:
        (GOLDEN_DIR / filename).write_text(build(), encoding="utf-8")
    print(f"{len(GOLDEN_CASES)}개 골든 파일을 {GOLDEN_DIR}에 썼다.")


if __name__ == "__main__":
    main()
