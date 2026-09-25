from api.core.config import settings
from api.core.security import hash_withdrawn_email


def test_hash_withdrawn_email_is_deterministic(monkeypatch: object) -> None:
    """재가입 차단은 조회라 같은 입력은 항상 같은
    해시를 내야 한다(salt가 있는 bcrypt로는 불가능한 성질)."""
    assert hash_withdrawn_email("user@example.com") == hash_withdrawn_email("user@example.com")


def test_hash_withdrawn_email_differs_for_different_emails() -> None:
    assert hash_withdrawn_email("a@example.com") != hash_withdrawn_email("b@example.com")


def test_hash_withdrawn_email_depends_on_the_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """순수 SHA-256이었다면 키를 바꿔도 같은 이메일의 해시가 그대로였을 것이다 — 이 테스트가
    실제로 키 있는 HMAC인지를 검증한다(양쪽에서 값이 달라야 논증이 된다)."""
    email = "user@example.com"
    original = hash_withdrawn_email(email)
    monkeypatch.setattr(settings, "withdrawn_email_hmac_key", "a-different-key")
    assert hash_withdrawn_email(email) != original
