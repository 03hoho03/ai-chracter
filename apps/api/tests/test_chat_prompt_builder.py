import uuid

from api.chat.prompt_builder import (
    CHARACTER_CHAT_SYSTEM_INSTRUCTION,
    STORY_CHAT_SYSTEM_INSTRUCTION,
    build_ending_judgment_prompt,
    build_generation_prompt,
    build_image_judgment_prompt,
    build_stat_judgment_prompt,
    build_story_generation_prompt,
    system_instruction_for,
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
        development_examples=[],
        user_goal=None,
        rules=None,
        custom_prompt=None,
        prologue="옛날 옛적 낯선 마을에 도착했다.",
        history=[],
        user_message="안녕!",
    )

    assert "세계관 설정" in prompt
    assert "[시작 상황]\n옛날 옛적 낯선 마을에 도착했다." in prompt
    assert prompt.endswith("사용자: 안녕!\n진행자:")


def test_build_story_generation_prompt_includes_development_examples_when_present() -> None:
    prompt = build_story_generation_prompt(
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text="세계관 설정",
        development_examples=[{"userLine": "안녕", "assistantLine": "어서오세요"}],
        user_goal=None,
        rules=None,
        custom_prompt=None,
        prologue="프롤로그",
        history=[],
        user_message="메시지",
    )

    assert "[전개 예시]\n사용자: 안녕\n서술자: 어서오세요" in prompt


def test_build_story_generation_prompt_joins_multiple_development_example_pairs() -> None:
    prompt = build_story_generation_prompt(
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text="세계관 설정",
        development_examples=[
            {"userLine": "첫 인사", "assistantLine": "첫 응답"},
            {"userLine": "둘째 인사", "assistantLine": "둘째 응답"},
        ],
        user_goal=None,
        rules=None,
        custom_prompt=None,
        prologue="프롤로그",
        history=[],
        user_message="메시지",
    )

    assert (
        "[전개 예시]\n사용자: 첫 인사\n서술자: 첫 응답\n사용자: 둘째 인사\n서술자: 둘째 응답" in prompt
    )


def test_build_story_generation_prompt_includes_rules_and_user_goal_between_setting_and_examples() -> None:
    """chat-techspec.md §6-3: L1 배치 순서는 setting_text → [규칙] → [사용자의 역할과 목표] →
    [전개 예시] → [시작 상황]이다."""
    prompt = build_story_generation_prompt(
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text="세계관 설정",
        development_examples=[{"userLine": "안녕", "assistantLine": "어서오세요"}],
        user_goal="용을 물리친다",
        rules="폭력 묘사는 암시로만 한다",
        custom_prompt=None,
        prologue="프롤로그",
        history=[],
        user_message="메시지",
    )

    assert "[규칙]\n폭력 묘사는 암시로만 한다" in prompt
    assert "[사용자의 역할과 목표]\n용을 물리친다" in prompt
    assert (
        prompt.index("세계관 설정")
        < prompt.index("[규칙]")
        < prompt.index("[사용자의 역할과 목표]")
        < prompt.index("[전개 예시]")
        < prompt.index("[시작 상황]")
    )


def test_build_story_generation_prompt_is_byte_identical_when_new_fields_are_empty() -> None:
    """chat-goal-prompt.md §8 '가장 중요한 제약': `rules`/`userGoal`/`developmentExamples`가
    비어 있으면(현재 시드 30개가 이 상태 — D-2) 이 함수의 출력은 그 필드들이 생기기 전과
    바이트 단위로 같아야 한다 — 아직 기준선 측정을 못 한 실험의 프롬프트를 건드리면 안 된다."""
    prompt = build_story_generation_prompt(
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text="세계관 설정",
        development_examples=[],
        user_goal=None,
        rules=None,
        custom_prompt=None,
        prologue="옛날 옛적 낯선 마을에 도착했다.",
        history=[],
        user_message="안녕!",
    )

    assert prompt == (
        "세계관 설정\n\n"
        "[시작 상황]\n옛날 옛적 낯선 마을에 도착했다.\n\n"
        "사용자: 안녕!\n진행자:"
    )
    assert "[규칙]" not in prompt
    assert "[사용자의 역할과 목표]" not in prompt
    assert "[전개 예시]" not in prompt


def test_migrated_development_example_pairs_reconstruct_to_the_original_free_text() -> None:
    """chat-goal-prompt.md §8 '가장 중요한 제약': 마이그레이션(리비전 ①)이 옛 자유 텍스트
    `development_example`을 쪼갠 쌍을, `build_story_generation_prompt`가 다시 조립했을 때
    원래 문자열이 나와야 한다 — 그래야 기존 시드 30개의 프롬프트가 안 바뀐다. 실측(발행 30개
    중 21개)으로 확인된 흔한 형식(단일 개행, `서술자:` 라벨)으로 이 성질이 성립함을 마이그레이션
    파일의 실제 파서로 못박는다. 나머지 9개는 창작자가 빈 줄(문단 구분)을 섞어 썼거나(5개) 안팎
    개행을 혼용했거나(3개) 순서가 뒤섞여(1개) 이 형식에서 벗어나 있고, 그 값들은 손실 없이
    보존되지만 재조립 결과가 원문과 바이트 단위로 같지는 않다(직접 DB 검증으로 확인, 42/60행)."""
    import importlib.util
    from pathlib import Path

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "45c1a3d8b69e_story_development_examples_user_goal_.py"
    )
    spec = importlib.util.spec_from_file_location("_migration_45c1a3d8b69e", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    original = (
        "사용자: 따뜻한 감자 스튜에 로즈마리를 살짝 얹어 하칸의 테이블에 내려놓는다.\n"
        "서술자: 하칸은 묵직한 김이 피어오르는 그릇을 멍하니 바라봅니다.\n"
        "사용자: 속이 편하셨다니 다행입니다.\n"
        "서술자: 아니, 이거면 됐다."
    )

    pairs = migration._parse_development_example(original)

    prompt = build_story_generation_prompt(
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text="세계관 설정",
        development_examples=pairs,
        user_goal=None,
        rules=None,
        custom_prompt=None,
        prologue="프롤로그",
        history=[],
        user_message="메시지",
    )

    reconstructed = prompt.split("[전개 예시]\n", 1)[1].split("\n\n[시작 상황]", 1)[0]
    assert reconstructed == original


def test_migrated_development_example_pairs_preserve_narration_before_the_first_user_label() -> None:
    """마이그레이션 파서는 첫 라벨의 *종류*가 아니라 텍스트가 사용자 라벨로 *시작하는지*를
    봐야 한다(모듈 docstring, chat-techspec.md §6-2). 첫 라벨이 `사용자:`라도 그 앞에 서술
    텍스트가 있으면 안전하게 재구성할 수 없으므로 원문 전체를 손실 없이 보존해야 한다."""
    import importlib.util
    from pathlib import Path

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "45c1a3d8b69e_story_development_examples_user_goal_.py"
    )
    spec = importlib.util.spec_from_file_location("_migration_45c1a3d8b69e", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    original = (
        "이것은 도입부 서술입니다. 배경 설명이 여기 들어갑니다.\n\n"
        "사용자: 안녕\n서술자: 반가워요"
    )

    pairs = migration._parse_development_example(original)

    assert pairs == [{"userLine": "", "assistantLine": original.strip()}]


def test_build_story_generation_prompt_custom_template_uses_custom_prompt_only() -> None:
    prompt = build_story_generation_prompt(
        prompt_template=StoryPromptTemplate.CUSTOM,
        setting_text="세계관 설정(무시되어야 함)",
        development_examples=[],
        user_goal=None,
        rules=None,
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
        development_examples=[],
        user_goal=None,
        rules=None,
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
        development_examples=[],
        user_goal=None,
        rules=None,
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
        development_examples=[],
        user_goal=None,
        rules=None,
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
        development_examples=[],
        user_goal=None,
        rules=None,
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


def test_base_system_instruction_covers_only_the_measured_gaps() -> None:
    """바닥 지시문은 "여러 작품이 똑같이 반복해 적는 것"(라벨 금지 29/30)과 "아무도 안 적어서
    서비스 기준이 어디에도 없는 것"(사용자 대사 대신쓰기 1/30, 수위 6/30)만 담는다.

    되받기 금지는 넣지 않는다 — 2026-08-11 에 90턴 전후 측정으로 세 기준 모두 노이즈
    범위였다. 톤·시점·길이도 넣지 않는다: 작품마다 정당하게 달라야 하고, 특히 길이는
    응답 중앙값이 18문장이라 임의의 상한이 30개의 연출을 통째로 바꾼다.
    """
    for text in (STORY_CHAT_SYSTEM_INSTRUCTION, CHARACTER_CHAT_SYSTEM_INSTRUCTION):
        assert "역할 표시로 시작하지 않는다" in text  # 29/30 이 각자 적던 것 — 여기로 모은다
        assert "대신 쓰지 않는다" in text  # 1/30
        assert "전연령" in text  # 6/30

        assert "되받" not in text, "되받기 금지는 무효로 측정됐다 — 되살리기 전에 재측정할 것"
        assert "문장" not in text, "문장 수 상한은 작품 연출을 침범한다 — 넣지 말 것"
        assert "인칭" not in text, "시점은 작품마다 다르다(wuxia-oneform 은 2인칭을 금지한다)"


def test_base_system_instruction_frames_each_chat_kind_as_its_own_speaker() -> None:
    """스토리 챗의 모델은 장면을 서술하는 화자이고, 캐릭터 챗의 모델은 캐릭터 본인이다.

    하나를 양쪽에 쓰면 캐릭터 챗의 모델이 자기를 해설자로 규정하게 된다. 금지할 라벨도
    그래서 갈린다 — 캐릭터 챗에서 새는 라벨은 "진행자:" 가 아니라 자기 이름이다.
    """
    assert "화자" in STORY_CHAT_SYSTEM_INSTRUCTION
    assert "캐릭터 본인" in CHARACTER_CHAT_SYSTEM_INSTRUCTION

    # 금지할 라벨을 예시로 적으면 그 토큰이 출력에 유도된다 — 2026-09-08 실측(아래 주석).
    for text in (STORY_CHAT_SYSTEM_INSTRUCTION, CHARACTER_CHAT_SYSTEM_INSTRUCTION):
        assert "진행자:" not in text
        assert "서술자:" not in text

    assert system_instruction_for(is_story_chat=True) == STORY_CHAT_SYSTEM_INSTRUCTION
    assert system_instruction_for(is_story_chat=False) == CHARACTER_CHAT_SYSTEM_INSTRUCTION


def test_base_system_instruction_keeps_the_turn_open() -> None:
    """[턴을 열어 둔다] — chat-goal-prompt.md §5. 프로덕션에서 관측된 "장면 닫기"(사용자
    발화 무시·길이 단조감소·인물 상태가 한 방향으로만 감)에 대한 처방으로, 스토리·캐릭터
    두 지시문이 공유하는 `_COMMON_RULES`에 들어간다.

    D-5: 금지 대상(닫는 행동)을 예시로 나열하지 않는다 — 2026-09-08 실측에서 라벨 금지에
    예시를 달았더니 없던 라벨이 새로 나타났다. 같은 위험이 있는 닫는 행동(잠들·자리를
    뜨·눈을 감)도 이름으로 적지 않는다. D-4: 길이·문장 수 상한도 넣지 않는다.
    """
    for text in (STORY_CHAT_SYSTEM_INSTRUCTION, CHARACTER_CHAT_SYSTEM_INSTRUCTION):
        assert "[턴을 열어 둔다]" in text

        assert "잠들" not in text
        assert "자리를 뜨" not in text
        assert "눈을 감" not in text

        assert "문장" not in text
