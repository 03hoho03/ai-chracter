"""되돌릴 수 있어야 하는 개인정보 칸(주민등록번호·계좌번호 등)을 앱 키로 암호화한다 — AES-256-GCM.

- 키 목록 문자열은 `kid:base64url(32바이트)[,kid:…]` 이다. **맨 앞 키로 암호화하고, 목록의 모든 키로 복호화한다.** 키를
  바꿀 때는 새 키를 맨 앞에 붙이고 옛 키를 뒤에 남겨, 옛 키로 만든 행을 다시 암호화할 때까지 읽을 수 있게 한다.
- 암호문 형식은 `nonce(12) ‖ ciphertext ‖ tag(16)` 이고, 어느 키로 만들었는지(kid)는 행의 칸에 따로 둔다.
- 연관 데이터(AAD)로 암호문을 그 자리(행·칸)에 묶는다. 다른 행이나 칸으로 옮긴 암호문은 복호화에 실패한다 — 암호문이
  다른 사람 행에 붙어 그 사람의 값처럼 읽히는 사고를 조용한 오답 대신 실패로 바꾼다.
- 실패는 `FieldDecryptError` 하나다. 예외 메시지에 값·키·암호문을 넣지 않는다(예외 메시지는 Bugsink 로 간다).

이 모듈은 설정을 읽지 않는다 — 설정 검증(`core/config.py`)이 같은 파서로 형식을 확인하고, 쓰는 쪽이 설정값을 넘긴다.
"""

import base64
import binascii
import os
import re
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32
NONCE_BYTES = 12
TAG_BYTES = 16

# 운영 `.env` 형식 검사기가 막는 문자(공백·따옴표·`$`·`\`)와 목록 구분자(`,`·`:`)를 키 id 에 쓰지 않는다.
_KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,32}")


class FieldDecryptError(Exception):
    """복호화할 수 없다 — 모르는 키 id, 망가진 암호문, 다른 자리(AAD)의 암호문, 맞지 않는 키."""

    def __init__(self) -> None:
        super().__init__("field ciphertext could not be decrypted")


@dataclass(frozen=True)
class FieldKeyring:
    # (키 id, 키) 순서 그대로. 맨 앞이 암호화 키다.
    keys: tuple[tuple[str, bytes], ...] = field(repr=False)

    @classmethod
    def parse(cls, raw: str) -> "FieldKeyring":
        """키 목록 문자열을 읽는다. 형식이 틀리면 `ValueError`(메시지에 키 값은 넣지 않는다)."""
        keys: list[tuple[str, bytes]] = []
        for index, entry in enumerate(raw.split(",")):
            key_id, sep, encoded = entry.partition(":")
            if not sep or not _KEY_ID.fullmatch(key_id):
                raise ValueError(f"key #{index + 1}: expected 'kid:base64url' with kid of [A-Za-z0-9_-]{{1,32}}")
            try:
                key = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            except (binascii.Error, ValueError):
                raise ValueError(f"key {key_id!r}: not base64url") from None
            if len(key) != KEY_BYTES:
                raise ValueError(f"key {key_id!r}: must decode to {KEY_BYTES} bytes")
            if any(existing == key_id for existing, _ in keys):
                raise ValueError(f"key {key_id!r}: duplicated")
            keys.append((key_id, key))
        return cls(tuple(keys))

    @property
    def current_key_id(self) -> str:
        return self.keys[0][0]

    def encrypt(self, plaintext: str, *, aad: bytes) -> tuple[str, bytes]:
        """맨 앞 키로 암호화한다. (그 키 id, `nonce ‖ ciphertext ‖ tag`)."""
        key_id, key = self.keys[0]
        nonce = os.urandom(NONCE_BYTES)
        return key_id, nonce + AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad)

    def decrypt(self, key_id: str, blob: bytes, *, aad: bytes) -> str:
        key = next((key for candidate, key in self.keys if candidate == key_id), None)
        if key is None or len(blob) < NONCE_BYTES + TAG_BYTES:
            raise FieldDecryptError
        try:
            plaintext = AESGCM(key).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], aad)
        except InvalidTag:
            raise FieldDecryptError from None
        return plaintext.decode("utf-8")
