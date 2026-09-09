from typing import Any

from pydantic import BaseModel

from api.db.models.character import SituationalImage
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.story import StatDef, StoryPromptTemplate


# 스토리·캐릭터 공통으로 생성 호출에 붙는 바닥 지시문(`LLMClient.generate(system_instruction=...)`).
#
# 이 자리가 비어 있던 동안 행동 규정은 100% 작가가 쓴 텍스트였고, 그 결과가 실측으로 갈렸다
# (2026-08-07, 시드 30개 settingText 전수 조사):
#   · 작가가 적은 규칙은 지켜진다 — 라벨 금지를 29/30이 각자 적었고 라벨 누출은 90턴 중 0건.
#   · 아무도 안 적은 규칙만 무너진다 — 사용자 대사 대신쓰기 금지 1/30, 수위 6/30.
# 그래서 여기 담는 것은 "여러 작품이 똑같이 반복해 적고 있는 것"(중복 제거)과 "아무도 안 적어서
# 서비스 기준이 어디에도 없는 것"(수위)뿐이다. 톤·시점·길이처럼 작품마다 정당하게 달라야 하는
# 것은 넣지 않는다 — 특히 길이는 응답 중앙값이 18문장이라, 임의의 문장 수 상한을 두면 30개의
# 연출을 통째로 바꾼다.
#
# 금지할 라벨을 예시로 나열하지 않는다("예: \"진행자:\", \"서술자:\"" 식). 2026-09-08 프로브에서
# 그 예시를 달았더니 지시문 없는 회차에는 없던 `(서술자: …)` 가 출력 첫 줄에 나타났다(10턴 중
# 1건, OFF 회차 0건) — 금지 대상을 적는 행위가 그 토큰을 프롬프트에 들여놓는다.
#
# 되받기 금지 규칙은 **의도적으로 빼 두었다.** 2026-08-11 에 같은 모델·대본으로 90턴을 전후
# 측정한 결과 세 기준 모두 노이즈 범위였다(앞 250자 70→73% / 앞 2문장 31→28% / 앞 30% 66→67%).
# 되받기는 프롬프트 문구가 아니라 매 턴 방 전체를 다시 붙이는 히스토리 구조 쪽에서 다시 본다.
#
# [턴을 열어 둔다]는 별개 문제의 처방이다(chat-goal-prompt.md §1-1~§1-3, §5). 프로덕션
# 대화록에서 모델이 매 턴 장면을 닫는 것(사용자 발화 무시·길이 단조감소·인물 상태가 한
# 방향으로만 감)이 관측됐고, 그 원인은 작품의 `settingText`/전개 예시였다 — 시스템 층에
# "턴을 열어 두라"는 규칙이 어디에도 없었다. D-5: 닫는 행동(잠들·자리를 뜨·눈을 감 등)을
# 예시로 나열하지 않는다 — 2026-09-08 실측에서 라벨 금지에 예시를 달았더니 없던 라벨이
# 새로 나타났다(위 문단). D-4: 길이·문장 수 상한은 넣지 않는다.
_COMMON_RULES = """[응답 형식]
응답을 화자 이름이나 역할 표시로 시작하지 않는다. 첫 글자부터 바로 서술이거나 대사다.

[사용자의 몫은 사용자가 정한다]
사용자의 대사·행동·선택·감정을 대신 쓰지 않는다. 사용자가 하지 않은 말을 인용하거나 했다고 단정하지 않는다.

[턴을 열어 둔다]
매 턴은 사용자가 다음에 할 수 있는 것을 최소 하나 남긴다 — 인물이 원하는 것, 방금 변한 상황, 새로 드러난 사실 중 하나면 된다. 인물이 냉담하거나 말을 아끼는 것은 작품의 자유다. 그 경우에도 장면은 움직인다: 다른 인물, 배경, 사용자가 손댈 수 있는 무언가 중 하나가 반응한다. 장면은 항상 사용자의 다음 행동을 기다리는 상태로 끝난다.

[수위]
전연령 서비스다. 선정적 묘사, 노골적인 신체 훼손, 자해 방법 묘사를 하지 않는다. 이 항목은 작품 설정보다 우선한다.

작품별 설정이 위 규칙보다 구체적인 지시를 하면 그 지시를 따른다(수위 항목은 예외)."""


STORY_CHAT_SYSTEM_INSTRUCTION = (
    "너는 사용자와 함께 이야기를 만들어 가는 화자다. 장면을 서술하고 그 안의 인물들을 연기한다.\n"
    "아래는 어떤 작품에서도 지켜야 하는 공통 규칙이다.\n\n"
    + _COMMON_RULES
)


CHARACTER_CHAT_SYSTEM_INSTRUCTION = (
    "너는 아래 설정으로 주어진 캐릭터 본인이다. 해설자가 아니라 그 인물로서 사용자와 일대일로 대화한다.\n"
    "아래는 어떤 캐릭터에게나 적용되는 공통 규칙이다.\n\n"
    + _COMMON_RULES
)


# L0.5 — 템플릿별 지시(chat-goal-prompt.md §6, D-6·D-7). L0(`_COMMON_RULES`)의 꼬리 문장
# ("작품별 설정이 위 규칙보다 구체적인 지시를 하면 그 지시를 따른다") **앞에** 끼워 넣는다 —
# 뒤에 붙이면 그 꼬리의 "위 규칙" 범위 밖에 놓여, 연출 지침인 템플릿 지시가 작품 설정보다
# 센 것으로 읽힌다(§5 설계 원칙: 작품 설정보다 약하되 형식은 강제한다). 프롬프트 본문(L1,
# 작품 설정)이 아니라 system_instruction에 두는 이유는 D-6: 본문에 이어 붙이면 작품 설정과
# 같은 층에 놓여 우선순위가 사라진다(`d6b726d`). 문안은 §6 표 그대로다 — 지어내지 않는다.
# `CUSTOM`은 `BASIC`과 같다(D-7: 커스텀은 *내용*의 전권이지 *형식*의 예외가 아니다).
_TEMPLATE_BASIC_INSTRUCTION = "매 턴 상황이 한 걸음 움직이고, 다음 장면으로 이어질 실마리를 남긴다."

_TEMPLATE_INSTRUCTIONS: dict[StoryPromptTemplate, str] = {
    StoryPromptTemplate.BASIC: _TEMPLATE_BASIC_INSTRUCTION,
    StoryPromptTemplate.EMOTIONAL: (
        "인물의 감정 변화가 사용자에게 읽히는 단서로 드러난다. 침묵도 반응이지만, "
        "그 침묵이 무엇을 뜻하는지 사용자가 짐작할 수 있어야 한다."
    ),
    StoryPromptTemplate.SIMULATION: (
        "이번 턴에 무엇이 변했는지 명시하고, 지금 사용자가 조작할 수 있는 것이 무엇인지 드러난다."
    ),
    StoryPromptTemplate.CUSTOM: _TEMPLATE_BASIC_INSTRUCTION,
}


def system_instruction_for(
    *, is_story_chat: bool, template: StoryPromptTemplate | None = None
) -> str:
    """생성 호출에 붙일 바닥 지시문을 챗 종류로 고르고, 스토리 챗이면 템플릿별 L0.5를 잇는다.

    스토리 챗의 모델은 장면 밖에서 서술하는 화자이고 캐릭터 챗의 모델은 캐릭터 본인이라,
    공통 규칙이 같아도 첫 줄의 자기 규정과 금지할 라벨이 다르다.

    `template`은 스토리 챗에서만 의미가 있다(D-17) — 캐릭터 챗은 템플릿 개념이 없으므로
    호출부가 넘기지 않는다(기본값 `None`). 스토리 챗 호출부가 `template`을 안 넘기면(기본값)
    L0.5 없이 L0까지만 반환한다.
    """
    base = STORY_CHAT_SYSTEM_INSTRUCTION if is_story_chat else CHARACTER_CHAT_SYSTEM_INSTRUCTION
    if template is None:
        return base
    # `base`는 `_COMMON_RULES`의 꼬리 문장으로 끝난다. 템플릿 지시를 그 꼬리 문장 뒤에
    # 이어 붙이면 "위 규칙"의 적용 범위 밖에 놓인다 — 꼬리 문장 앞(마지막 "\n\n" 앞)에
    # 끼워 넣어 다시 마지막 줄이 꼬리 문장이 되게 한다.
    rules, _, tail = base.rpartition("\n\n")
    return rules + "\n\n" + _TEMPLATE_INSTRUCTIONS[template] + "\n\n" + tail


def build_generation_prompt(
    *,
    character_prompt: str,
    example_dialogues: list[dict[str, Any]],
    history: list[ChatMessage],
    user_message: str,
) -> str:
    """techspec-backend-chat.md §3.1 buildGenerationPrompt — 캐릭터 챗 전용.

    캐릭터 프롬프트 뒤에 예시 대화("말투 예시")를 매 턴 포함하고, 최근 메시지
    히스토리와 이번 턴의 사용자 메시지로 마무리한다.
    """
    sections = [character_prompt]

    if example_dialogues:
        example_lines = "\n".join(
            f"사용자: {pair['userLine']}\n캐릭터: {pair['characterLine']}" for pair in example_dialogues
        )
        sections.append(f"[말투 예시]\n{example_lines}")

    if history:
        history_lines = "\n".join(
            f"{'사용자' if message.role == ChatMessageRole.USER else '캐릭터'}: {message.content}"
            for message in history
        )
        sections.append(f"[대화 기록]\n{history_lines}")

    sections.append(f"사용자: {user_message}\n캐릭터:")

    return "\n\n".join(sections)


def build_story_generation_prompt(
    *,
    prompt_template: StoryPromptTemplate,
    setting_text: str | None,
    development_examples: list[dict[str, Any]],
    user_goal: str | None,
    rules: str | None,
    custom_prompt: str | None,
    prologue: str,
    history: list[ChatMessage],
    user_message: str,
    keyword_note_texts: list[str] | None = None,
    shortcut_prompt: str | None = None,
) -> str:
    """techspec-backend-chat.md §3.1 buildGenerationPrompt — 스토리 챗 전용.

    "스토리 설정 템플릿+시작설정 프롤로그" 뒤에 매칭된 키워드북 정보(사용자에게는
    비노출, `match_keyword_notes`로 이미 걸러진 결과만 받음), 최근 히스토리, (단축어
    실행 시) 단축어 프롬프트, 이번 턴의 사용자 메시지 순으로 마무리한다.

    chat-goal-prompt.md §8 / chat-techspec.md §6-3 (D-16): `rules`·`user_goal`·
    `development_examples`는 L1 작품 층이라 설정 텍스트 바로 뒤, [시작 상황] 앞에 붙는다.
    셋 다 비어 있으면(현재 시드 30개가 전부 이 상태다 — D-2) 이 함수는 이 인자들을
    추가하기 전과 바이트 단위로 같은 프롬프트를 낸다 — 각 섹션이 `if 값:` 으로 감싸여
    있어 헤더조차 나타나지 않기 때문이다(`keyword_note_texts`/`shortcut_prompt`와 같은
    패턴). `development_examples`는 옛 자유 텍스트 컬럼(`development_example`)을 대신한다
    — 마이그레이션이 그 텍스트를 이 쌍 목록으로 백필하므로, 이 함수가 만드는 [전개 예시]
    문자열이 옛 자유 텍스트와 같아야 기존 시드의 프롬프트가 안 바뀐다.
    """
    sections: list[str] = []

    if prompt_template == StoryPromptTemplate.CUSTOM:
        if custom_prompt:
            sections.append(custom_prompt)
    elif setting_text:
        sections.append(setting_text)

    if rules:
        sections.append(f"[규칙]\n{rules}")
    if user_goal:
        sections.append(f"[사용자의 역할과 목표]\n{user_goal}")
    if development_examples:
        example_lines = "\n".join(
            f"사용자: {pair['userLine']}\n서술자: {pair['assistantLine']}" for pair in development_examples
        )
        sections.append(f"[전개 예시]\n{example_lines}")

    sections.append(f"[시작 상황]\n{prologue}")

    if keyword_note_texts:
        sections.append("[키워드북]\n" + "\n".join(keyword_note_texts))

    if history:
        history_lines = "\n".join(
            f"{'사용자' if message.role == ChatMessageRole.USER else '진행자'}: {message.content}"
            for message in history
        )
        sections.append(f"[대화 기록]\n{history_lines}")

    if shortcut_prompt:
        sections.append(f"[단축어]\n{shortcut_prompt}")

    sections.append(f"사용자: {user_message}\n진행자:")

    return "\n\n".join(sections)


def build_stat_judgment_prompt(
    *,
    stat_defs: list[StatDef],
    current_stats: dict[str, float],
    history: list[ChatMessage],
    user_message: str,
    assistant_message: str,
) -> str:
    """techspec-backend-chat.md §3.1 buildJudgmentPrompt — 스탯 변경 판단(스토리 챗 전용).

    스탯 정의(설명/범위/현재값)와 이번 턴까지의 대화를 근거로 LLMClient.generateStructured()가
    StatJudgmentResult(구조화 출력)로 각 스탯의 변경 여부를 판단하게 한다.
    """
    # `per_turn_delta`가 있는 스탯은 `apply_stat_changes`가 매 턴 결정적으로 굴리고 LLM 판단은
    # 무시된다. 그래도 현재값은 서사 판단의 근거이므로 목록에는 남기고, 판단 대상이 아니라는
    # 것만 표시해 불필요한 출력을 줄인다.
    stat_lines = "\n".join(
        f"- statId={stat_def.entity_id}, 이름={stat_def.name}, 설명={stat_def.description}, "
        f"범위=[{stat_def.min_value}, {stat_def.max_value}], "
        f"현재값={current_stats.get(str(stat_def.entity_id), stat_def.initial_value)}"
        + ("  ※ 시스템이 매 턴 자동 조정하는 값이다. statChanges에 넣지 마라." if stat_def.per_turn_delta is not None else "")
        for stat_def in stat_defs
    )

    turn_lines = [
        f"{'사용자' if message.role == ChatMessageRole.USER else '진행자'}: {message.content}"
        for message in history
    ]
    turn_lines.append(f"사용자: {user_message}")
    turn_lines.append(f"진행자: {assistant_message}")

    return (
        "다음은 스토리 챗의 스탯 정의와 현재 값이다.\n"
        f"{stat_lines}\n\n"
        "[대화 기록]\n" + "\n".join(turn_lines) + "\n\n"
        "위 대화, 특히 마지막 사용자 행동과 그에 대한 응답을 근거로 각 스탯이 이번 턴에 "
        "어떻게 변해야 하는지 판단하라. 변화가 없는 스탯은 statChanges에 포함하지 않아도 된다. "
        "newValue는 항상 그 스탯의 최종 절대값으로 응답하라. "
        # "매 턴 반드시 N씩" 카운터는 `per_turn_delta`로 코드가 굴리므로 여기서 지시하지
        # 않는다. 남는 건 "사건이 일어날 때만 한 방향으로 움직이는" 스탯(몸 손상, 남은 씨앗
        # 등)인데, 그 제약은 여전히 description 산문뿐이라 코드가 막지 못한다 — 최소한
        # 연출 지침이 아니라 규칙이라는 것만 못박아 둔다(강제가 아니라 완화).
        "각 스탯 설명에 적힌 증감 제약은 연출 지침이 아니라 반드시 지켜야 하는 규칙이다. "
        "'절대 늘어나지 않는다'고 적힌 스탯은 현재값보다 큰 값을 내지 말고, "
        "'절대 감소하지 않는다'고 적힌 스탯은 현재값보다 작은 값을 내지 마라."
    )


class StatChangeJudgment(BaseModel):
    stat_id: str
    new_value: float


class StatJudgmentResult(BaseModel):
    """techspec-backend-chat.md §3.1 판단용 response_schema — 스탯 변경."""

    stat_changes: list[StatChangeJudgment]


def build_ending_judgment_prompt(
    *,
    judgment_prompt: str,
    history: list[ChatMessage],
    user_message: str,
    assistant_message: str,
) -> str:
    """techspec-backend-chat.md §3.1 buildJudgmentPrompt — 엔딩 판정(스토리 챗 전용).

    엔딩 하나의 judgment_prompt(판정 기준)와 이번 턴까지의 대화를 근거로
    LLMClient.generateStructured()가 EndingJudgmentResult(구조화 출력)로 그 엔딩의
    발동 조건 충족 여부를 판단하게 한다. 여러 엔딩이 있으면 이 함수를 엔딩별로 호출한다.
    """
    turn_lines = [
        f"{'사용자' if message.role == ChatMessageRole.USER else '진행자'}: {message.content}"
        for message in history
    ]
    turn_lines.append(f"사용자: {user_message}")
    turn_lines.append(f"진행자: {assistant_message}")

    return (
        "다음은 스토리 챗의 대화 기록이다.\n\n"
        "[대화 기록]\n" + "\n".join(turn_lines) + "\n\n"
        "아래는 하나의 엔딩이 발동하기 위한 판정 기준이다. 지금까지의 대화가 이 기준을 "
        "충족하는지 판단하라.\n"
        f"[판정 기준]\n{judgment_prompt}"
    )


class EndingJudgmentResult(BaseModel):
    """techspec-backend-chat.md §3.1 판단용 response_schema — 엔딩 판정."""

    triggered: bool


def build_image_judgment_prompt(
    *,
    situational_images: list[SituationalImage],
    history: list[ChatMessage],
    user_message: str,
    assistant_message: str,
) -> str:
    """techspec-backend-chat.md §3.1 buildJudgmentPrompt — 상황별 이미지 매칭(캐릭터 챗 전용).

    등록된 이미지의 노출 조건(trigger_condition)과 이번 턴까지의 대화를 근거로
    LLMClient.generateStructured()가 ImageMatchJudgmentResult(구조화 출력)로 매칭되는 이미지가
    있는지 판단하게 한다. 목록을 order 오름차순으로 제시하고, 여러 조건이 동시에 충족돼도
    응답은 항상 단수이므로 더 앞(우선순위가 높은) 이미지 하나만 고르도록 명시적으로 지시한다
    (techspec-chat-character.md §1.1 "동시 매칭 처리").
    """
    image_lines = "\n".join(
        f"- imageEntityId={image.entity_id}, 노출 조건={image.trigger_condition}"
        for image in situational_images
    )

    turn_lines = [
        f"{'사용자' if message.role == ChatMessageRole.USER else '캐릭터'}: {message.content}"
        for message in history
    ]
    turn_lines.append(f"사용자: {user_message}")
    turn_lines.append(f"캐릭터: {assistant_message}")

    return (
        "다음은 이 캐릭터에 등록된 상황별 이미지 목록이다(우선순위가 높은 순서로 나열됨).\n"
        f"{image_lines}\n\n"
        "[대화 기록]\n" + "\n".join(turn_lines) + "\n\n"
        "위 대화, 특히 마지막 사용자 행동과 그에 대한 캐릭터의 응답을 근거로 이번 턴에 노출 "
        "조건이 충족된 이미지가 있는지 판단하라. 여러 이미지의 조건이 동시에 충족되면 목록에서 "
        "더 앞에 있는(우선순위가 높은) 이미지 하나만 선택하라. 조건을 충족하는 이미지가 없으면 "
        "matchedImageEntityId를 null로 응답하라."
    )


class ImageMatchJudgmentResult(BaseModel):
    """techspec-backend-chat.md §3.1 판단용 response_schema — 상황별 이미지 매칭(캐릭터 챗 전용)."""

    matched_image_entity_id: str | None
