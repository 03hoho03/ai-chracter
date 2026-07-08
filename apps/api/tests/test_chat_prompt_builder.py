import uuid

from api.chat.prompt_builder import build_generation_prompt
from api.db.models.chat import ChatMessage, ChatMessageRole


def _message(role: ChatMessageRole, content: str) -> ChatMessage:
    return ChatMessage(chat_room_id=uuid.uuid4(), role=role, content=content)


def test_build_generation_prompt_includes_character_prompt_only_when_no_extras() -> None:
    prompt = build_generation_prompt(
        character_prompt="너는 다정한 고양이 캐릭터야.",
        example_dialogues=[],
        history=[],
        user_message="안녕!",
    )

    assert "너는 다정한 고양이 캐릭터야." in prompt
    assert "말투 예시" not in prompt
    assert "대화 기록" not in prompt
    assert prompt.endswith("사용자: 안녕!\n캐릭터:")


def test_build_generation_prompt_includes_example_dialogues_as_speech_style() -> None:
    prompt = build_generation_prompt(
        character_prompt="캐릭터 프롬프트",
        example_dialogues=[{"userLine": "밥 먹었어?", "characterLine": "냐옹! 아직이야옹"}],
        history=[],
        user_message="다음 메시지",
    )

    assert "[말투 예시]" in prompt
    assert "사용자: 밥 먹었어?" in prompt
    assert "캐릭터: 냐옹! 아직이야옹" in prompt


def test_build_generation_prompt_includes_history_in_order() -> None:
    history = [
        _message(ChatMessageRole.ASSISTANT, "안녕하세요"),
        _message(ChatMessageRole.USER, "반가워요"),
    ]

    prompt = build_generation_prompt(
        character_prompt="캐릭터 프롬프트",
        example_dialogues=[],
        history=history,
        user_message="다음 메시지",
    )

    history_section = prompt.split("[대화 기록]\n", 1)[1]
    assert history_section.startswith("캐릭터: 안녕하세요\n사용자: 반가워요")


def test_build_generation_prompt_appends_user_message_last() -> None:
    prompt = build_generation_prompt(
        character_prompt="캐릭터 프롬프트",
        example_dialogues=[{"userLine": "a", "characterLine": "b"}],
        history=[_message(ChatMessageRole.USER, "이전 메시지")],
        user_message="이번 메시지",
    )

    assert prompt.rstrip().endswith("사용자: 이번 메시지\n캐릭터:")
