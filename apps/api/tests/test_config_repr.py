"""설정 객체의 repr 은 필드 이름만 내고 값은 내지 않는다.

테스트가 실패하면 pytest 가 설정 객체의 repr 을 메시지에 그대로 싣는 경로가 있다 — 없는 속성을
`monkeypatch.setattr` 하면 나는 `AttributeError`, 단언 실패 표시. 그 출력이 로그·에이전트 산출물에
남으면 비밀로 표시하지 않은 값(인프라 주소·공개 식별자)도 함께 새어 나간다. 필드마다 비밀 여부를
고르는 대신 repr 전체에서 값을 뺀다.
"""

import pytest

from api.core.config import Settings

# 실제 주소처럼 보이지 않는 고유 문자열 — 출력에 이 문자열이 있으면 값이 샌 것이다.
_MARKER = "redis://repr-marker-7f3a.invalid:6379/0"


def _settings_with_marker() -> Settings:
    # 작업 폴더의 env 파일을 읽지 않는다 — 실패 출력에 실제 설정 값이 섞이지 않게.
    return Settings(_env_file=None, redis_url=_MARKER)  # type: ignore[call-arg]


def test_repr_and_str_show_field_names_but_not_values() -> None:
    """repr·str 은 어떤 설정이 있는지는 보여 주되 그 값은 드러내지 않는다."""
    settings = _settings_with_marker()

    for rendered in (repr(settings), str(settings)):
        assert _MARKER not in rendered
        assert "redis_url" in rendered


def test_monkeypatch_typo_error_does_not_reveal_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """없는 속성 이름을 패치하면 pytest 가 대상 객체 repr 을 오류 메시지에 싣는다 — 그 메시지에 값이 없어야 한다."""
    settings = _settings_with_marker()

    with pytest.raises(AttributeError) as excinfo:
        monkeypatch.setattr(settings, "no_such_setting_name", 1)

    message = str(excinfo.value)
    assert "no_such_setting_name" in message
    assert _MARKER not in message


def test_failed_assertion_message_does_not_reveal_values() -> None:
    """단언이 실패하면 pytest 가 피연산자 repr 을 실패 메시지에 싣는다 — 그 메시지에 값이 없어야 한다.

    `==` 비교는 pytest 의 비교 설명 훅이 피연산자를 짧게 잘라 표지가 우연히 빠질 수 있어, 피연산자 repr 을
    그대로 싣는 `not` 단언을 쓴다. 메시지가 앞부분을 남기고 자르므로 표지는 repr 에서 맨 앞에 나오는
    표시 필드에 넣었다.
    """
    settings = _settings_with_marker()

    with pytest.raises(AssertionError) as excinfo:
        assert not settings  # type: ignore[truthy-bool]  # 늘 참인 객체라 이 단언은 반드시 실패한다 — 의도다

    message = str(excinfo.value)
    # 단언 재작성이 꺼져 있으면 메시지가 비어 표지 검사가 거짓으로 통과한다 — repr 이 실제로 실렸는지 먼저 본다.
    assert "redis_url" in message
    assert _MARKER not in message
