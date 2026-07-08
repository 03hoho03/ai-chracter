from typing import Any

from api.db.models.chat import ChatMessage, ChatMessageRole


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
