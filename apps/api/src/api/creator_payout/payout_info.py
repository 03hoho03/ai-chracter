"""크리에이터 지급 정보(실명·주민등록번호·은행·계좌번호)의 검증·암호화·마스킹.

암호문은 행 id 와 칸 이름을 연관 데이터로 묶는다 — 다른 행이나 칸으로 옮긴 암호문은 복호화에 실패한다. 복호화한 값은
응답 밖(로그·예외 메시지·Bugsink)으로 내보내지 않는다. 검증 실패는 이유만 돌려주고 값은 싣지 않는다.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, get_args

from api.core.field_crypto import FieldKeyring
from api.db.models.creator_payout import BankCode, CreatorPayoutProfile

_BANK_CODES: dict[str, BankCode] = {code: code for code in get_args(BankCode)}

LEGAL_NAME_MAX_LENGTH = 40
_RRN = re.compile(r"[0-9]{13}")
_ACCOUNT_NUMBER = re.compile(r"[0-9]{6,20}")

# 주민등록번호 7번째 자리(성별·세기) → 출생 세기. 5~8 은 외국인등록번호다.
_CENTURY_BY_RRN_DIGIT = {"9": 1800, "0": 1800, "1": 1900, "2": 1900, "3": 2000, "4": 2000}
_FOREIGNER_RRN_DIGITS = frozenset("5678")

PayoutInfoRefusal = Literal["invalid", "foreigner", "rrn_mismatch"]

EncryptedColumn = Literal["legal_name", "rrn", "account_number"]
_ENCRYPTED_COLUMNS: tuple[EncryptedColumn, ...] = get_args(EncryptedColumn)


@dataclass(frozen=True)
class PayoutInfo:
    """검증을 마친 지급 정보. repr 에 값을 싣지 않는다(예외·로그에 객체가 찍혀도 값이 나가지 않게)."""

    legal_name: str = field(repr=False)
    rrn: str = field(repr=False)
    bank_code: BankCode
    account_number: str = field(repr=False)


def parse_payout_info(
    *, legal_name: str, rrn: str, bank_code: str, account_number: str, birth_date: date | None
) -> PayoutInfo | PayoutInfoRefusal:
    """형식 → 외국인등록번호 → 주민등록번호 앞 7자리(생년월일 + 세기)와 본인인증 생년월일 대조 순으로 보고, 받을 수
    없으면 그 이유를 돌려준다. 실명은 앞뒤 공백을 뺀 뒤 1~40자다. 주민등록번호 끝자리 검증식은 쓰지 않는다 — 2020년
    10월 뒤 발급분은 뒤 6자리가 임의 번호라 검증식이 맞지 않는다."""
    name = legal_name.strip()
    bank = _BANK_CODES.get(bank_code)
    if (
        not 1 <= len(name) <= LEGAL_NAME_MAX_LENGTH
        or not _RRN.fullmatch(rrn)
        or bank is None
        or not _ACCOUNT_NUMBER.fullmatch(account_number)
    ):
        return "invalid"
    if rrn[6] in _FOREIGNER_RRN_DIGITS:
        return "foreigner"
    if birth_date is None or _rrn_birth_date(rrn) != birth_date:
        return "rrn_mismatch"
    return PayoutInfo(legal_name=name, rrn=rrn, bank_code=bank, account_number=account_number)


def _rrn_birth_date(rrn: str) -> date | None:
    """내국인 주민등록번호(7번째 자리 0~4·9)의 생년월일. 없는 날짜면 `None`."""
    century = _CENTURY_BY_RRN_DIGIT[rrn[6]]
    try:
        return date(century + int(rrn[0:2]), int(rrn[2:4]), int(rrn[4:6]))
    except ValueError:
        return None


def _aad(profile_id: uuid.UUID, column: EncryptedColumn) -> bytes:
    return b"creator_payout_profile:" + profile_id.bytes + b":" + column.encode()


def new_profile(
    keyring: FieldKeyring,
    info: PayoutInfo,
    *,
    user_id: uuid.UUID,
    consented_at: datetime,
    privacy_version: str,
) -> CreatorPayoutProfile:
    """암호화한 새 지급 정보 판. id 를 먼저 정해야 연관 데이터에 넣을 수 있다."""
    profile_id = uuid.uuid4()
    key_id, name_blob = keyring.encrypt(info.legal_name, aad=_aad(profile_id, "legal_name"))
    _, rrn_blob = keyring.encrypt(info.rrn, aad=_aad(profile_id, "rrn"))
    _, account_blob = keyring.encrypt(info.account_number, aad=_aad(profile_id, "account_number"))
    return CreatorPayoutProfile(
        id=profile_id,
        user_id=user_id,
        key_id=key_id,
        legal_name_ciphertext=name_blob,
        rrn_ciphertext=rrn_blob,
        account_number_ciphertext=account_blob,
        bank_code=info.bank_code,
        account_last4=info.account_number[-4:],
        consented_at=consented_at,
        privacy_version=privacy_version,
    )


def decrypt_field(keyring: FieldKeyring, profile: CreatorPayoutProfile, column: EncryptedColumn) -> str:
    """한 칸을 복호화한다. 실패하면 `FieldDecryptError`."""
    blob: bytes = getattr(profile, f"{column}_ciphertext")
    return keyring.decrypt(profile.key_id, blob, aad=_aad(profile.id, column))


def reencrypt_profile(keyring: FieldKeyring, profile: CreatorPayoutProfile) -> None:
    """세 칸을 지금 암호화 키로 다시 쓴다(값은 같다). 세 칸을 모두 복호화한 뒤에 쓰므로 하나라도 실패하면 행이 그대로다."""
    plaintexts = {column: decrypt_field(keyring, profile, column) for column in _ENCRYPTED_COLUMNS}
    for column, plaintext in plaintexts.items():
        profile.key_id, blob = keyring.encrypt(plaintext, aad=_aad(profile.id, column))
        setattr(profile, f"{column}_ciphertext", blob)


def mask_name(name: str) -> str:
    """첫 글자와 끝 글자만 남긴다(홍길동 → 홍*동, 2자는 홍*)."""
    if len(name) <= 1:
        return "*"
    if len(name) == 2:
        return name[0] + "*"
    return name[0] + "*" * (len(name) - 2) + name[-1]
