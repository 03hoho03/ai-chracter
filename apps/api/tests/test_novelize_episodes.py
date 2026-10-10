"""묶음의 화 수 계산과 모델별 묶음 상한 — 순수 함수라 DB 없이 본다.

경계는 값 하나로 보지 않는다. 반올림 경계는 바로 아래·정확히 위 두 값을, 상한은 모델마다 서로 다른 값을 넣어 어느
모델의 설정을 읽었는지 가려지게 한다(모델마다 같은 값이면 설정을 바꿔 읽어도 테스트가 통과한다)."""

import uuid
from datetime import UTC, datetime

import pytest

from api.chat.prompt_builder import PromptNames
from api.core.config import Settings, settings
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.llm.chat_models import ChatModelId
from api.novelize.episodes import chapter_max_turns, episode_count, k_max, regenerate_ineligibility, source_chars
from api.novelize.source import SourceTurn


@pytest.fixture(autouse=True)
def _known_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novelize_source_ratio", 0.8)
    monkeypatch.setattr(settings, "novelize_episode_target_chars", 5000)


def _distinct_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novelize_k_max_gemini", 3)
    monkeypatch.setattr(settings, "novelize_k_max_sonnet", 2)
    monkeypatch.setattr(settings, "novelize_k_max_opus", 4)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", 45)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns_sonnet", 25)
    monkeypatch.setattr(settings, "novelize_chapter_max_turns_opus", 15)


def test_defaults_are_the_provisional_values() -> None:
    """임시값을 바꾸면 화 단가 계산·작업 상한 근거가 함께 바뀌므로 기본값을 고정해 둔다."""
    fields = Settings.model_fields
    assert [fields[f"novelize_k_max_{m}"].default for m in ("gemini", "sonnet", "opus")] == [3, 1, 1]
    assert [
        fields[name].default
        for name in (
            "novelize_chapter_max_turns",
            "novelize_chapter_max_turns_sonnet",
            "novelize_chapter_max_turns_opus",
        )
    ] == [45, 20, 20]
    assert (fields["novelize_episode_target_chars"].default, fields["novelize_source_ratio"].default) == (5000, 0.8)


def test_each_model_reads_its_own_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    _distinct_limits(monkeypatch)
    models: list[ChatModelId] = ["gemini", "sonnet", "opus"]
    assert [k_max(m) for m in models] == [3, 2, 4]
    assert [chapter_max_turns(m) for m in models] == [45, 25, 15]


@pytest.mark.parametrize(
    ("chars", "expected"),
    [
        pytest.param(0, 1, id="nothing-is-still-one"),
        pytest.param(3124, 1, id="just-under-half-of-one"),  # 0.4998 → 0 → 1 로 올림
        pytest.param(9374, 1, id="just-under-1.5"),  # 1.49984
        pytest.param(9375, 2, id="exactly-1.5-rounds-up"),
        pytest.param(15624, 2, id="just-under-2.5"),  # 2.49984
        pytest.param(15625, 3, id="exactly-2.5-rounds-up"),
        pytest.param(21875, 3, id="exactly-3.5-is-capped"),
        pytest.param(10**6, 3, id="far-over-is-capped"),
    ],
)
def test_gemini_episode_count_rounds_half_up_and_clamps(
    monkeypatch: pytest.MonkeyPatch, chars: int, expected: int
) -> None:
    _distinct_limits(monkeypatch)
    assert episode_count(chars, "gemini") == expected


@pytest.mark.parametrize(
    ("model", "chars", "expected"),
    [
        pytest.param("sonnet", 9374, 1, id="sonnet-under-1.5"),
        pytest.param("sonnet", 9375, 2, id="sonnet-at-its-cap"),
        pytest.param("sonnet", 15625, 2, id="sonnet-capped-at-2"),
        pytest.param("opus", 21874, 3, id="opus-under-3.5"),
        pytest.param("opus", 21875, 4, id="opus-at-its-cap"),
        pytest.param("opus", 10**6, 4, id="opus-capped-at-4"),
    ],
)
def test_claude_episode_count_uses_its_own_cap(
    monkeypatch: pytest.MonkeyPatch, model: ChatModelId, chars: int, expected: int
) -> None:
    _distinct_limits(monkeypatch)
    assert episode_count(chars, model) == expected


def test_default_claude_caps_make_every_batch_one_episode() -> None:
    claude: list[ChatModelId] = ["sonnet", "opus"]
    assert [episode_count(chars, m) for m in claude for chars in (9375, 10**6)] == [1, 1, 1, 1]


def test_ratio_is_read_as_its_decimal_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """0.7 × 22,500 ÷ 4,500 은 정확히 3.5 다 — 부동소수로 계산하면 3.4999… 가 되어 3 으로 내려간다."""
    monkeypatch.setattr(settings, "novelize_source_ratio", 0.7)
    monkeypatch.setattr(settings, "novelize_episode_target_chars", 4500)
    monkeypatch.setattr(settings, "novelize_k_max_gemini", 9)
    assert (episode_count(22499, "gemini"), episode_count(22500, "gemini")) == (3, 4)


def _message(role: ChatMessageRole, content: str) -> ChatMessage:
    return ChatMessage(id=uuid.uuid4(), role=role, content=content, created_at=datetime.now(UTC))


def test_source_chars_counts_what_the_model_reads() -> None:
    """이미지 태그는 빼고 작가 글 이름은 바꾼 글자로 센다. 사용자 줄의 `{{user}}` 는 사용자가 친 글자라 그대로 센다."""
    names = PromptNames(persona_name="서진", char_name="도윤")
    turns = [
        SourceTurn(users=(), assistant=_message(ChatMessageRole.ASSISTANT, "  {{char}}가 웃었다. ")),
        SourceTurn(
            users=(_message(ChatMessageRole.USER, "{{user}} 안녕"),),
            assistant=_message(ChatMessageRole.ASSISTANT, "{{img::11111111-1111-4111-8111-111111111111}}{{user}}, 왔어?"),
        ),
    ]
    # "도윤이 웃었다." 8 + "{{user}} 안녕" 11 + "서진, 왔어?" 7 — 조사도 이름에 맞춰 바뀐다
    assert source_chars(turns, names) == 8 + 11 + 7


@pytest.mark.parametrize(
    ("model", "episodes", "turns", "expected"),
    [
        pytest.param("gemini", 3, 45, None, id="gemini-fits-its-own-batch"),
        pytest.param("sonnet", 2, 25, None, id="sonnet-at-both-caps"),
        pytest.param("sonnet", 3, 25, "too_many_episodes", id="sonnet-one-episode-over"),
        pytest.param("sonnet", 2, 26, "too_many_turns", id="sonnet-one-turn-over"),
        pytest.param("opus", 4, 15, None, id="opus-at-both-caps"),
        pytest.param("opus", 4, 16, "too_many_turns", id="opus-one-turn-over"),
    ],
)
def test_regenerate_ineligibility_checks_the_models_own_caps(
    monkeypatch: pytest.MonkeyPatch, model: ChatModelId, episodes: int, turns: int, expected: str | None
) -> None:
    _distinct_limits(monkeypatch)
    assert regenerate_ineligibility(model, episode_count=episodes, turn_count=turns) == expected
