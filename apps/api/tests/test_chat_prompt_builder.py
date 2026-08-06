import uuid

from api.chat.prompt_builder import (
    build_ending_judgment_prompt,
    build_generation_prompt,
    build_image_judgment_prompt,
    build_stat_judgment_prompt,
    build_story_generation_prompt,
)
from api.db.models.character import SituationalImage
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


def _situational_image(**overrides: object) -> SituationalImage:
    defaults: dict[str, object] = {
        "entity_id": uuid.uuid4(),
        "content_version_id": uuid.uuid4(),
        "image_asset_id": uuid.uuid4(),
        "blurred_asset_id": uuid.uuid4(),
        "trigger_condition": "캐릭터가 웃을 때",
        "order": 1,
    }
    defaults.update(overrides)
    return SituationalImage(**defaults)


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


def test_build_image_judgment_prompt_lists_images_in_order_with_trigger_conditions() -> None:
    low_priority = _situational_image(order=1, trigger_condition="캐릭터가 화날 때")
    high_priority = _situational_image(order=0, trigger_condition="캐릭터가 웃을 때")

    prompt = build_image_judgment_prompt(
        situational_images=[low_priority, high_priority],
        history=[],
        user_message="재밌는 얘기 해줘",
        assistant_message="하하, 정말 웃기지 않아?",
    )

    # 인자 순서와 무관하게, 호출부가 넘긴 순서(=order로 미리 정렬된 순서)를 그대로 나열한다.
    assert prompt.index(str(low_priority.entity_id)) < prompt.index(str(high_priority.entity_id))
    assert f"imageEntityId={low_priority.entity_id}, 노출 조건=캐릭터가 화날 때" in prompt
    assert f"imageEntityId={high_priority.entity_id}, 노출 조건=캐릭터가 웃을 때" in prompt
    assert "재밌는 얘기 해줘" in prompt
    assert "하하, 정말 웃기지 않아?" in prompt


def test_build_image_judgment_prompt_includes_history_before_this_turn() -> None:
    history = [_message(ChatMessageRole.USER, "이전 메시지")]

    prompt = build_image_judgment_prompt(
        situational_images=[_situational_image()],
        history=history,
        user_message="이번 메시지",
        assistant_message="이번 응답",
    )

    history_section = prompt.split("[대화 기록]\n", 1)[1]
    assert history_section.splitlines()[:3] == ["사용자: 이전 메시지", "사용자: 이번 메시지", "캐릭터: 이번 응답"]


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


def test_build_stat_judgment_prompt_binds_the_direction_constraints_in_descriptions() -> None:
    """"절대 늘지 않는다" / "매 턴 반드시 줄어든다" 류 제약은 스탯 `description` 의 산문일
    뿐이고 `apply_stat_changes` 는 min/max clamp 만 한다 — 코드가 강제하지 못하는 구간이다.

    실측(2026-08-07): `wuxia-oneform` 의 '남은 날' 이 26→27 로 **올랐고**(정의상 금지),
    `romance-3rdloop` 의 '남은 방송 회차' 는 여러 턴 감소를 건너뛰었다. 엔딩이 이런 카운터에
    걸려 있으면(wuxia 엔딩 2·3 은 `남은 날<=0`) 도달 가능성이 통째로 흔들린다. 완전한 해결은
    스탯에 방향 필드를 두고 코드로 막는 것이지만, 그 전까지 최소한 판정 프롬프트가 이 제약을
    연출 지침이 아닌 규칙으로 못박고 있어야 한다.
    """
    prompt = build_stat_judgment_prompt(
        stat_defs=[_stat_def(name="남은 날", description="매 턴 반드시 1일씩 줄어들며 절대 늘어나지 않는다")],
        current_stats={},
        history=[],
        user_message="수련한다",
        assistant_message="뼈가 부서진다",
    )

    assert "반드시 지켜야 하는 규칙" in prompt
    assert "현재값보다 큰 값을 내지 말고" in prompt


def test_build_stat_judgment_prompt_marks_system_managed_counters() -> None:
    """`per_turn_delta` 스탯은 `apply_stat_changes` 가 굴리고 LLM 판단은 버려진다 —
    현재값은 서사 판단의 근거라 목록엔 남기되, 판단 대상이 아님을 표시해 헛수고를 줄인다."""
    counter = _stat_def(name="산소", description="밀실의 산소")
    counter.per_turn_delta = -5
    judged = _stat_def(name="상호 신뢰", description="서로에 대한 신뢰")

    prompt = build_stat_judgment_prompt(
        stat_defs=[counter, judged],
        current_stats={},
        history=[],
        user_message="문을 두드린다",
        assistant_message="아무도 답하지 않는다",
    )

    oxygen_line = next(line for line in prompt.splitlines() if "이름=산소" in line)
    trust_line = next(line for line in prompt.splitlines() if "이름=상호 신뢰" in line)
    assert "statChanges에 넣지 마라" in oxygen_line
    assert "statChanges에 넣지 마라" not in trust_line
