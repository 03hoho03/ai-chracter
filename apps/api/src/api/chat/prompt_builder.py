from typing import Any

from pydantic import BaseModel

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
) -> str:
    """techspec-backend-chat.md §3.1 buildGenerationPrompt — 스토리 챗 전용.

    "스토리 설정 템플릿+시작설정 프롤로그" 뒤에 최근 히스토리와 이번 턴의 사용자
    메시지로 마무리한다(캐릭터의 예시 대화 주입에 대응하는 스토리 전용 섹션은
    없음 — 키워드북/단축어 주입은 별도 스토리(US-064/065) 범위).
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

    if history:
        history_lines = "\n".join(
            f"{'사용자' if message.role == ChatMessageRole.USER else '진행자'}: {message.content}"
            for message in history
        )
        sections.append(f"[대화 기록]\n{history_lines}")

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
    stat_lines = "\n".join(
        f"- statId={stat_def.entity_id}, 이름={stat_def.name}, 설명={stat_def.description}, "
        f"범위=[{stat_def.min_value}, {stat_def.max_value}], "
        f"현재값={current_stats.get(str(stat_def.entity_id), stat_def.initial_value)}"
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
        "newValue는 항상 그 스탯의 최종 절대값으로 응답하라."
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
