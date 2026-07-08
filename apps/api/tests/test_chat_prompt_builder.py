import uuid

from api.chat.prompt_builder import (
    build_ending_judgment_prompt,
    build_generation_prompt,
    build_stat_judgment_prompt,
    build_story_generation_prompt,
)
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.story import StatDef, StoryPromptTemplate


def _message(role: ChatMessageRole, content: str) -> ChatMessage:
    return ChatMessage(chat_room_id=uuid.uuid4(), role=role, content=content)


def _stat_def(**overrides: object) -> StatDef:
    defaults: dict[str, object] = {
        "entity_id": uuid.uuid4(),
        "starting_setup_id": uuid.uuid4(),
        "name": "호감도",
        "icon": "heart",
        "color": "#ff0000",
        "min_value": 0,
        "max_value": 100,
        "initial_value": 50,
        "unit": None,
        "description": "호감도 스탯",
        "order": 1,
    }
    defaults.update(overrides)
    return StatDef(**defaults)


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


def test_build_story_generation_prompt_uses_setting_text_and_prologue() -> None:
    prompt = build_story_generation_prompt(
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text="세계관 설정",
        development_example=None,
        custom_prompt=None,
        prologue="옛날 옛적 낯선 마을에 도착했다.",
        history=[],
        user_message="안녕!",
    )

    assert "세계관 설정" in prompt
    assert "[시작 상황]\n옛날 옛적 낯선 마을에 도착했다." in prompt
    assert prompt.endswith("사용자: 안녕!\n진행자:")


def test_build_story_generation_prompt_includes_development_example_when_present() -> None:
    prompt = build_story_generation_prompt(
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text="세계관 설정",
        development_example="전개 예시 텍스트",
        custom_prompt=None,
        prologue="프롤로그",
        history=[],
        user_message="메시지",
    )

    assert "[전개 예시]\n전개 예시 텍스트" in prompt


def test_build_story_generation_prompt_custom_template_uses_custom_prompt_only() -> None:
    prompt = build_story_generation_prompt(
        prompt_template=StoryPromptTemplate.CUSTOM,
        setting_text="세계관 설정(무시되어야 함)",
        development_example=None,
        custom_prompt="커스텀 프롬프트",
        prologue="프롤로그",
        history=[],
        user_message="메시지",
    )

    assert "커스텀 프롬프트" in prompt
    assert "세계관 설정(무시되어야 함)" not in prompt


def test_build_story_generation_prompt_includes_matched_keyword_notes() -> None:
    prompt = build_story_generation_prompt(
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text="세계관 설정",
        development_example=None,
        custom_prompt=None,
        prologue="프롤로그",
        history=[],
        user_message="메시지",
        keyword_note_texts=["마법사는 사실 왕자다"],
    )

    assert "[키워드북]\n마법사는 사실 왕자다" in prompt


def test_build_story_generation_prompt_omits_keyword_note_section_when_no_match() -> None:
    prompt = build_story_generation_prompt(
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text="세계관 설정",
        development_example=None,
        custom_prompt=None,
        prologue="프롤로그",
        history=[],
        user_message="메시지",
        keyword_note_texts=[],
    )

    assert "[키워드북]" not in prompt


def test_build_story_generation_prompt_includes_shortcut_prompt_before_final_turn() -> None:
    prompt = build_story_generation_prompt(
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text="세계관 설정",
        development_example=None,
        custom_prompt=None,
        prologue="프롤로그",
        history=[],
        user_message="메시지",
        shortcut_prompt="주변을 수색한다",
    )

    assert "[단축어]\n주변을 수색한다" in prompt
    assert prompt.rstrip().endswith("사용자: 메시지\n진행자:")


def test_build_story_generation_prompt_includes_history_in_order() -> None:
    history = [
        _message(ChatMessageRole.ASSISTANT, "안녕하세요"),
        _message(ChatMessageRole.USER, "반가워요"),
    ]

    prompt = build_story_generation_prompt(
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text="세계관 설정",
        development_example=None,
        custom_prompt=None,
        prologue="프롤로그",
        history=history,
        user_message="다음 메시지",
    )

    history_section = prompt.split("[대화 기록]\n", 1)[1]
    assert history_section.startswith("진행자: 안녕하세요\n사용자: 반가워요")


def test_build_stat_judgment_prompt_includes_stat_definitions_and_current_values() -> None:
    stat_def = _stat_def(name="호감도", description="캐릭터에 대한 호감도", min_value=0, max_value=100)

    prompt = build_stat_judgment_prompt(
        stat_defs=[stat_def],
        current_stats={str(stat_def.entity_id): 50.0},
        history=[],
        user_message="칭찬했다",
        assistant_message="기뻐했다",
    )

    assert f"statId={stat_def.entity_id}" in prompt
    assert "이름=호감도" in prompt
    assert "설명=캐릭터에 대한 호감도" in prompt
    assert "범위=[0, 100]" in prompt
    assert "현재값=50.0" in prompt
    assert "사용자: 칭찬했다" in prompt
    assert "진행자: 기뻐했다" in prompt


def test_build_stat_judgment_prompt_falls_back_to_initial_value_when_stat_not_seeded() -> None:
    stat_def = _stat_def(initial_value=30)

    prompt = build_stat_judgment_prompt(
        stat_defs=[stat_def],
        current_stats={},
        history=[],
        user_message="메시지",
        assistant_message="응답",
    )

    assert "현재값=30" in prompt


def test_build_stat_judgment_prompt_includes_history_before_this_turn() -> None:
    history = [_message(ChatMessageRole.USER, "이전 메시지")]

    prompt = build_stat_judgment_prompt(
        stat_defs=[],
        current_stats={},
        history=history,
        user_message="이번 메시지",
        assistant_message="이번 응답",
    )

    history_section = prompt.split("[대화 기록]\n", 1)[1]
    assert history_section.splitlines()[:3] == ["사용자: 이전 메시지", "사용자: 이번 메시지", "진행자: 이번 응답"]


def test_build_ending_judgment_prompt_includes_criteria_and_this_turn() -> None:
    prompt = build_ending_judgment_prompt(
        judgment_prompt="주인공이 마을을 완전히 떠났는가?",
        history=[],
        user_message="마을을 떠났다",
        assistant_message="주인공은 마을을 뒤로하고 떠났다.",
    )

    assert "[판정 기준]\n주인공이 마을을 완전히 떠났는가?" in prompt
    assert "사용자: 마을을 떠났다" in prompt
    assert "진행자: 주인공은 마을을 뒤로하고 떠났다." in prompt


def test_build_ending_judgment_prompt_includes_history_before_this_turn() -> None:
    history = [_message(ChatMessageRole.USER, "이전 메시지")]

    prompt = build_ending_judgment_prompt(
        judgment_prompt="기준",
        history=history,
        user_message="이번 메시지",
        assistant_message="이번 응답",
    )

    history_section = prompt.split("[대화 기록]\n", 1)[1]
    assert history_section.splitlines()[:3] == ["사용자: 이전 메시지", "사용자: 이번 메시지", "진행자: 이번 응답"]
