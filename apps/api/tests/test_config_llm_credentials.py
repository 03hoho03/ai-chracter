"""Claude 자격 목록 저장소의 env 세 키 — 암호화 키 목록·허용 계정 목록의 형식 검사와 비밀 칸의 가림.

형식이 틀린 값은 기동을 막는다(틀린 키로 암호화하거나 오타 난 허용 목록이 "아무 계정도 허용 안 함"으로 조용히 남는 것보다
뜨지 않는 편이 낫다). 오류 문장에는 값을 싣지 않는다 — 기동 로그와 Bugsink 로 간다."""

import base64

import pytest
from pydantic import ValidationError

from api.core.config import Settings
from api.llm.credential_accounts import parse_allowed_accounts
from factories import FAKE_CREDENTIAL_KEYRING, load_production_env


def _settings(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> Settings:
    # 작업 폴더의 env 파일을 읽지 않는다 — 실패 출력에 실제 설정 값이 섞이지 않게.
    monkeypatch.setenv(name, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("k1:" + base64.urlsafe_b64encode(b"\x07" * 16).decode(), id="short-key"),
        pytest.param("k1" + base64.urlsafe_b64encode(b"\x07" * 32).decode(), id="no-kid-separator"),
        pytest.param("k1:" + "!" * 43, id="not-base64"),
        pytest.param(f"{FAKE_CREDENTIAL_KEYRING},{FAKE_CREDENTIAL_KEYRING}", id="duplicated-kid"),
    ],
)
def test_malformed_credential_keyring_refuses_to_boot_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    with pytest.raises(ValidationError) as caught:
        _settings(monkeypatch, "LLM_CREDENTIAL_ENCRYPTION_KEYS", raw)

    assert "llm_credential_encryption_keys" in str(caught.value)
    assert raw.rsplit(":", 1)[-1] not in str(caught.value)


_ORG = "org-test-0001"
_AWS = "123456789012"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("", frozenset(), id="empty-is-nothing-allowed"),
        pytest.param(
            f"  anthropic:{_ORG} , aws:{_AWS}  ",
            frozenset({("anthropic", _ORG), ("aws", _AWS)}),
            id="spaces-around-entries-are-dropped",
        ),
        pytest.param(
            f"anthropic:{_ORG},,aws:{_AWS},", frozenset({("anthropic", _ORG), ("aws", _AWS)}), id="empty-entries"
        ),
        pytest.param("anthropic:Org-Test-0001", frozenset({("anthropic", _ORG)}), id="anthropic-id-is-lowercased"),
        pytest.param(f"Anthropic:{_ORG}", "provider must be 'anthropic' or 'aws'", id="provider-is-case-sensitive"),
        pytest.param(f"AWS:{_AWS}", "provider must be 'anthropic' or 'aws'", id="aws-is-case-sensitive"),
        pytest.param(f"gcp:{_ORG}", "provider must be 'anthropic' or 'aws'", id="unknown-provider"),
        pytest.param(_ORG, "expected 'provider:id'", id="no-separator"),
        pytest.param("anthropic:", "entry #1: anthropic id", id="empty-anthropic-id"),
        pytest.param('anthropic:org"x', "entry #1: anthropic id", id="anthropic-id-with-a-quote"),
        pytest.param("anthropic:" + "a" * 65, "entry #1: anthropic id", id="anthropic-id-too-long"),
        pytest.param("aws:12345678901", "entry #1: aws id", id="aws-11-digits"),
        pytest.param("aws:12345678901a", "entry #1: aws id", id="aws-not-digits"),
        pytest.param(f"anthropic:{_ORG},aws:{_AWS},anthropic:ORG-TEST-0001", "entry #3: duplicated", id="duplicate"),
    ],
)
def test_allowed_accounts_parsing(raw: str, expected: frozenset[tuple[str, str]] | str) -> None:
    """공급자 토큰은 소문자 그대로만 받는다 — 너그럽게 받으면 오타가 기동을 통과해 "아무것도 허용 안 됨"으로 조용히
    남는다. 조직 id 는 글자 집합만 보고 소문자로 맞춘다(응답 헤더도 같은 정규화 뒤 비교한다)."""
    if isinstance(expected, str):
        with pytest.raises(ValueError, match=expected):
            parse_allowed_accounts(raw)
    else:
        assert parse_allowed_accounts(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("anthropic:org-leak-marker,anthropic:org-leak-marker", id="duplicate"),
        pytest.param("anthropic:org-leak-marker x", id="bad-anthropic-id"),
        pytest.param("aws:org-leak-marker", id="bad-aws-id"),
        pytest.param("org-leak-marker", id="no-separator"),
    ],
)
def test_allowed_accounts_errors_do_not_echo_values(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    """틀린 허용 목록은 기동을 막되, 오류 문장에는 항목 번호와 공급자 종류만 있고 조직 id 는 없다."""
    with pytest.raises(ValidationError) as caught:
        _settings(monkeypatch, "LLM_CREDENTIAL_ALLOWED_ACCOUNTS", raw)

    assert "llm_credential_allowed_accounts" in str(caught.value)
    assert "leak-marker" not in str(caught.value)


def test_production_env_with_credential_store_keys_still_boots(monkeypatch: pytest.MonkeyPatch) -> None:
    """운영 env 에 세 키를 더해도 뜬다 — 형식 검사가 운영 env 의 다른 키와 엮여 기동을 막지 않는다."""
    loaded = load_production_env(
        monkeypatch,
        LLM_CREDENTIAL_ENCRYPTION_KEYS=FAKE_CREDENTIAL_KEYRING,
        LLM_CREDENTIAL_ALLOWED_ACCOUNTS=f"anthropic:{_ORG}",
        LLM_CREDENTIAL_DISCORD_WEBHOOK_URL="https://discord.invalid/api/webhooks/0/test",
    )

    assert loaded.llm_credential_encryption_keys == FAKE_CREDENTIAL_KEYRING
    assert parse_allowed_accounts(loaded.llm_credential_allowed_accounts) == frozenset({("anthropic", _ORG)})
    assert loaded.llm_credential_discord_webhook_url == "https://discord.invalid/api/webhooks/0/test"


def test_new_secret_settings_are_hidden_from_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    """암호화 키 목록과 웹훅 주소(주소가 곧 그 채널에 쓸 권한)는 비밀이라 repr 에 이름조차 나오지 않는다."""
    monkeypatch.setenv("LLM_CREDENTIAL_ENCRYPTION_KEYS", FAKE_CREDENTIAL_KEYRING)
    loaded = _settings(monkeypatch, "LLM_CREDENTIAL_DISCORD_WEBHOOK_URL", "https://discord.invalid/hook-marker")
    rendered = repr(loaded)

    assert loaded.llm_credential_discord_webhook_url == "https://discord.invalid/hook-marker"
    for name in ("llm_credential_encryption_keys", "llm_credential_discord_webhook_url"):
        assert Settings.model_fields[name].repr is False
        assert name not in rendered
    assert "hook-marker" not in rendered
    assert FAKE_CREDENTIAL_KEYRING.rsplit(":", 1)[-1] not in rendered
