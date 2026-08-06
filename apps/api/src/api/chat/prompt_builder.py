from typing import Any

from pydantic import BaseModel

from api.db.models.character import SituationalImage
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.story import StatDef, StoryPromptTemplate


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
    development_example: str | None,
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
    """
    sections: list[str] = []

    if prompt_template == StoryPromptTemplate.CUSTOM:
        if custom_prompt:
            sections.append(custom_prompt)
    elif setting_text:
        setting_section = setting_text
        if development_example:
            setting_section = f"{setting_section}\n\n[전개 예시]\n{development_example}"
        sections.append(setting_section)

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
