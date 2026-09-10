"""prompt-db-goal-prompt.md D-17. 조립 결과를 되읊는 테스트는 골든 대조
(`tests/test_prompt_goldens.py`)가 이미 바이트 단위로 증명하므로 지웠다 — 여기 남기는
것은 렌더러 자체의 분기뿐이다: 조건부 드롭·`order` 정렬·`scope` 필터·`variant` 선택·
라벨 매핑(`story_assistant_label`/`character_assistant_label`/`story_example_label`을
안 섞는지). `PromptSection`/`PromptSet`은 DB 세션 없이 생성자로만 채운다
(`nullable=False`는 DB 제약일 뿐이라 이 테스트들이 안 쓰는 필드는 생략한다).

라벨 매핑 테스트는 네 라벨을 전부 다른 문자열로 둔다 — 값이 같으면 "다른 컬럼을 읽었다"는
사실을 어떤 assert도 구분하지 못하는 항진명제가 된다. 히스토리에는 USER/ASSISTANT를
섞는다 — 역할 삼항이 한쪽 분기로만 치우치면(예: ASSISTANT만) 반대쪽 라벨이 깨져도 테스트가
안 죽는다(2026-09-08 뮤테이션 테스트가 실제로 잡은 패턴).
"""

import uuid

from api.chat.prompt_builder import (
    build_ending_judgment_prompt,
    build_generation_prompt,
    build_image_judgment_prompt,
    build_stat_judgment_prompt,
    build_story_generation_prompt,
    render_prompt_channel,
    system_instruction_for,
)
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import StoryPromptTemplate


def _message(role: ChatMessageRole, content: str) -> ChatMessage:
    return ChatMessage(chat_room_id=uuid.uuid4(), role=role, content=content)


def _section(
    *, channel: str, scope: str, slot: str, body: str, conditional: bool, order: int, variant: str = ""
) -> PromptSection:
    return PromptSection(
        channel=channel, scope=scope, slot=slot, variant=variant, body=body, conditional=conditional, order=order
    )


def _prompt_set(**overrides: object) -> PromptSet:
    defaults: dict[str, object] = {
        "status": "published",
        "user_label": "사용자레이블",
        "story_assistant_label": "진행자레이블",
        "story_example_label": "서술자레이블",
        "character_assistant_label": "캐릭터레이블",
    }
    defaults.update(overrides)
    return PromptSet(**defaults)


# ---- render_prompt_channel — 렌더러 코어 -----------------------------------


def test_render_prompt_channel_drops_conditional_section_when_value_is_empty() -> None:
    sections = [
        _section(
            channel="generation", scope="both", slot="history",
            body="[대화 기록]\n{history_lines}", conditional=True, order=1,
        ),
    ]
    result = render_prompt_channel(sections, channel="generation", scope="character", values={"history_lines": ""})
    assert result == ""


def test_render_prompt_channel_keeps_non_conditional_section_when_value_is_empty() -> None:
    """§4-3 실측: "비어 있으면 드롭"만으로는 재현되지 않는다 — `conditional=False` 슬롯은
    빈 값이어도 섹션 자체(와 그 앞의 `\\n\\n` 구분자)가 남는다(`generation_character_empty_prompt`
    골든이 이 사실의 증거)."""
    sections = [
        _section(
            channel="generation", scope="character", slot="character_prompt",
            body="{character_prompt}", conditional=False, order=1,
        ),
        _section(
            channel="generation", scope="both", slot="final_frame",
            body="{user_label}:", conditional=False, order=2,
        ),
    ]
    result = render_prompt_channel(
        sections, channel="generation", scope="character",
        values={"character_prompt": "", "user_label": "사용자"},
    )
    assert result == "\n\n사용자:"


def test_render_prompt_channel_sorts_by_order_regardless_of_input_order() -> None:
    sections = [
        _section(channel="system", scope="both", slot="second", body="B", conditional=False, order=2),
        _section(channel="system", scope="both", slot="first", body="A", conditional=False, order=1),
    ]
    result = render_prompt_channel(sections, channel="system", scope="story", values={})
    assert result == "A\n\nB"


def test_render_prompt_channel_filters_by_scope() -> None:
    sections = [
        _section(channel="system", scope="story", slot="story_only", body="STORY", conditional=False, order=1),
        _section(channel="system", scope="character", slot="character_only", body="CHAR", conditional=False, order=2),
        _section(channel="system", scope="both", slot="shared", body="SHARED", conditional=False, order=3),
    ]
    story_result = render_prompt_channel(sections, channel="system", scope="story", values={})
    character_result = render_prompt_channel(sections, channel="system", scope="character", values={})

    assert story_result == "STORY\n\nSHARED"
    assert character_result == "CHAR\n\nSHARED"


def test_render_prompt_channel_omits_variant_only_slot_without_a_matching_variant() -> None:
    """`template_instruction`처럼 `variant=''` 기본 행이 아예 없는 슬롯은, 요청한 variant가
    없으면(기본값 `''`) 슬롯째 빠진다 — `system_instruction_for(template=None)`이 L0.5 없이
    L0까지만 반환하는 것과 같은 동작이다."""
    sections = [
        _section(
            channel="system", scope="story", slot="template_instruction",
            body="BASIC", conditional=False, order=1, variant="basic",
        ),
        _section(
            channel="system", scope="story", slot="template_instruction",
            body="EMOTIONAL", conditional=False, order=1, variant="emotional",
        ),
    ]
    without_template = render_prompt_channel(sections, channel="system", scope="story", values={})
    with_template = render_prompt_channel(sections, channel="system", scope="story", variant="basic", values={})

    assert without_template == ""
    assert with_template == "BASIC"


def test_render_prompt_channel_falls_back_to_default_variant_when_requested_variant_is_absent() -> None:
    """`base_content`처럼 기본(`variant=''`) 행과 특정 variant 행이 공존하는 슬롯은, 요청한
    variant가 그 슬롯에 없으면 기본 행으로 대체한다 — 스토리 BASIC/EMOTIONAL/SIMULATION
    템플릿이 전부 같은 `{setting_text}` 행을 쓰고 CUSTOM만 `{custom_prompt}` 행을 쓰는 이유다."""
    sections = [
        _section(
            channel="generation", scope="story", slot="base_content",
            body="{setting_text}", conditional=True, order=1, variant="",
        ),
        _section(
            channel="generation", scope="story", slot="base_content",
            body="{custom_prompt}", conditional=True, order=1, variant="custom",
        ),
    ]
    values = {"setting_text": "SETTING", "custom_prompt": "CUSTOM"}
    basic = render_prompt_channel(sections, channel="generation", scope="story", variant="", values=values)
    custom = render_prompt_channel(sections, channel="generation", scope="story", variant="custom", values=values)

    assert basic == "SETTING"
    assert custom == "CUSTOM"


def test_render_prompt_channel_default_variant_fallback_drops_section_when_value_is_empty() -> None:
    """§9-2 R-2 사각지대(적대적 리뷰가 시드 body로 재현) — `base_content`처럼 기본
    (`variant=''`) 행이 있는 슬롯도, 요청한 variant(`custom`)가 없어 그 기본 행으로
    폴백했는데 기본 행이 참조하는 값이 비어 있으면 `conditional=True`인 이 섹션은
    통째로 드롭된다. CUSTOM 템플릿 스토리는 `setting_text`가 비어 있는 게 정상이라
    이 경로가 실제로 도달 가능하다 — "다른 문안으로 대체"가 아니라 "슬롯 소실"이라는
    뜻이다(위 폴백 테스트는 `setting_text`를 채운 값으로만 확인해 이 사각지대를
    못 잡았다)."""
    sections = [
        _section(
            channel="generation", scope="story", slot="base_content",
            body="{setting_text}", conditional=True, order=1, variant="",
        ),
    ]
    values = {"setting_text": "", "custom_prompt": "CUSTOM"}
    rendered = render_prompt_channel(sections, channel="generation", scope="story", variant="custom", values=values)

    assert rendered == ""


# ---- system_instruction_for — scope/variant 배선 ---------------------------


def test_system_instruction_for_selects_scope_and_variant() -> None:
    sections = [
        _section(channel="system", scope="story", slot="self_definition", body="STORY_SELF", conditional=False, order=1),
        _section(channel="system", scope="character", slot="self_definition", body="CHAR_SELF", conditional=False, order=1),
        _section(
            channel="system", scope="story", slot="template_instruction",
            body="BASIC", conditional=False, order=2, variant="basic",
        ),
    ]
    assert system_instruction_for(sections, is_story_chat=False) == "CHAR_SELF"
    assert system_instruction_for(sections, is_story_chat=True, template=None) == "STORY_SELF"
    assert (
        system_instruction_for(sections, is_story_chat=True, template=StoryPromptTemplate.BASIC)
        == "STORY_SELF\n\nBASIC"
    )


# ---- 라벨 매핑 — build_* 가 올바른 컬럼을 읽는지 ----------------------------


def test_build_generation_prompt_uses_character_labels_not_story_labels() -> None:
    prompt_set = _prompt_set()
    sections = [
        _section(
            channel="generation", scope="character", slot="example_dialogues",
            body="[말투 예시]\n{example_lines}", conditional=True, order=2,
        ),
        _section(
            channel="generation", scope="both", slot="history",
            body="[대화 기록]\n{history_lines}", conditional=True, order=6,
        ),
        _section(
            channel="generation", scope="both", slot="final_frame",
            body="{user_label}: {user_message}\n{assistant_label}:", conditional=False, order=9,
        ),
    ]
    prompt = build_generation_prompt(
        prompt_set=prompt_set,
        sections=sections,
        character_prompt="",
        example_dialogues=[{"userLine": "안녕", "characterLine": "응"}],
        history=[
            _message(ChatMessageRole.ASSISTANT, "이전 응답"),
            _message(ChatMessageRole.USER, "이전 메시지"),
        ],
        user_message="이번 메시지",
    )

    assert f"{prompt_set.user_label}: 안녕" in prompt
    assert f"{prompt_set.character_assistant_label}: 응" in prompt
    assert f"{prompt_set.character_assistant_label}: 이전 응답" in prompt
    assert f"{prompt_set.user_label}: 이전 메시지" in prompt
    assert prompt.endswith(f"{prompt_set.user_label}: 이번 메시지\n{prompt_set.character_assistant_label}:")
    assert prompt_set.story_assistant_label not in prompt
    assert prompt_set.story_example_label not in prompt


def test_build_story_generation_prompt_uses_example_label_only_for_development_examples() -> None:
    """§1-1: 전개 예시 자리만 `story_example_label`("서술자")을 쓰고, 대화 기록·마지막
    프레임은 `story_assistant_label`("진행자")을 쓴다 — 같은 스토리 챗인데 자리마다 라벨이
    갈리는 것은 표류가 아니라 실측된 현재 동작이라 섞이면 안 된다."""
    prompt_set = _prompt_set()
    sections = [
        _section(
            channel="generation", scope="story", slot="development_examples",
            body="[전개 예시]\n{example_lines}", conditional=True, order=4,
        ),
        _section(
            channel="generation", scope="both", slot="history",
            body="[대화 기록]\n{history_lines}", conditional=True, order=6,
        ),
        _section(
            channel="generation", scope="both", slot="final_frame",
            body="{user_label}: {user_message}\n{assistant_label}:", conditional=False, order=9,
        ),
    ]
    prompt = build_story_generation_prompt(
        prompt_set=prompt_set,
        sections=sections,
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text=None,
        development_examples=[{"userLine": "안녕", "assistantLine": "환영"}],
        user_goal=None,
        rules=None,
        custom_prompt=None,
        prologue="",
        history=[
            _message(ChatMessageRole.ASSISTANT, "이전 응답"),
            _message(ChatMessageRole.USER, "이전 메시지"),
        ],
        user_message="이번 메시지",
    )

    assert f"{prompt_set.story_example_label}: 환영" in prompt
    assert f"{prompt_set.story_assistant_label}: 이전 응답" in prompt
    assert f"{prompt_set.user_label}: 이전 메시지" in prompt
    assert prompt.endswith(f"{prompt_set.user_label}: 이번 메시지\n{prompt_set.story_assistant_label}:")
    # 라벨이 섞이지 않았는지 개수로 못박는다 — story_example_label 은 전개 예시 한 곳에만.
    assert prompt.count(prompt_set.story_example_label) == 1
    assert prompt.count(prompt_set.story_assistant_label) == 2  # 히스토리 1 + 마지막 프레임 1
    assert prompt_set.character_assistant_label not in prompt


def test_build_stat_judgment_prompt_uses_story_assistant_label() -> None:
    prompt_set = _prompt_set()
    sections = [
        _section(
            channel="stat_judgment", scope="story", slot="turn_context",
            body="[대화 기록]\n{user_label}: {user_message}\n{assistant_label}: {assistant_message}",
            conditional=False, order=2,
        ),
    ]
    prompt = build_stat_judgment_prompt(
        prompt_set=prompt_set, sections=sections, stat_defs=[], current_stats={},
        user_message="메시지", assistant_message="응답",
    )

    assert f"{prompt_set.story_assistant_label}: 응답" in prompt
    assert prompt_set.character_assistant_label not in prompt
    assert prompt_set.story_example_label not in prompt


def test_build_ending_judgment_prompt_uses_story_assistant_label_for_history_and_this_turn() -> None:
    prompt_set = _prompt_set()
    sections = [
        _section(
            channel="ending_judgment", scope="story", slot="turn_context",
            body="[대화 기록]\n{turn_lines}", conditional=False, order=2,
        ),
    ]
    prompt = build_ending_judgment_prompt(
        prompt_set=prompt_set,
        sections=sections,
        judgment_prompt="기준",
        history=[
            _message(ChatMessageRole.ASSISTANT, "이전 응답"),
            _message(ChatMessageRole.USER, "이전 메시지"),
        ],
        user_message="이번 메시지",
        assistant_message="이번 응답",
    )

    assert f"{prompt_set.story_assistant_label}: 이전 응답" in prompt
    assert f"{prompt_set.user_label}: 이전 메시지" in prompt
    assert f"{prompt_set.story_assistant_label}: 이번 응답" in prompt
    assert prompt_set.character_assistant_label not in prompt
    assert prompt_set.story_example_label not in prompt


def test_build_image_judgment_prompt_uses_character_assistant_label() -> None:
    prompt_set = _prompt_set()
    sections = [
        _section(
            channel="image_judgment", scope="character", slot="turn_context",
            body="[대화 기록]\n{turn_lines}", conditional=False, order=2,
        ),
    ]
    prompt = build_image_judgment_prompt(
        prompt_set=prompt_set,
        sections=sections,
        situational_images=[],
        history=[
            _message(ChatMessageRole.ASSISTANT, "이전 응답"),
            _message(ChatMessageRole.USER, "이전 메시지"),
        ],
        user_message="이번 메시지",
        assistant_message="이번 응답",
    )

    assert f"{prompt_set.character_assistant_label}: 이전 응답" in prompt
    assert f"{prompt_set.user_label}: 이전 메시지" in prompt
    assert f"{prompt_set.character_assistant_label}: 이번 응답" in prompt
    assert prompt_set.story_assistant_label not in prompt
    assert prompt_set.story_example_label not in prompt


# ---- 마이그레이션 파서 왕복 (이 파일과 무관한 별도 회귀 — build_story_generation_prompt는
# 검증 도구로만 쓰인다) ------------------------------------------------------


def _development_examples_prompt_set_and_sections() -> tuple[PromptSet, list[PromptSection]]:
    prompt_set = _prompt_set(user_label="사용자", story_example_label="서술자")
    sections = [
        _section(
            channel="generation", scope="story", slot="development_examples",
            body="[전개 예시]\n{example_lines}", conditional=True, order=4,
        ),
    ]
    return prompt_set, sections


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

    prompt_set, sections = _development_examples_prompt_set_and_sections()
    prompt = build_story_generation_prompt(
        prompt_set=prompt_set,
        sections=sections,
        prompt_template=StoryPromptTemplate.BASIC,
        setting_text=None,
        development_examples=pairs,
        user_goal=None,
        rules=None,
        custom_prompt=None,
        prologue="",
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
