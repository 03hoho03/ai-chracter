"""Claude 자격 목록에 넣을 수 있는 계정의 허용 목록(`LLM_CREDENTIAL_ALLOWED_ACCOUNTS`)을 읽는다.

형식은 `anthropic:<조직 id>,aws:<계정 id>` 쉼표 목록이다. 항목 앞뒤 공백과 빈 항목은 버리고, 빈 목록은 정상 값(아무 계정도
허용하지 않음)이다. 공급자 토큰은 소문자 그대로만 받는다 — 너그럽게 받으면 오타가 기동을 통과해 "아무것도 허용 안 됨"으로
조용히 남는다. Anthropic 조직 id 는 형식 근거가 없어 UUID 를 강제하지 않고 글자 집합만 보며(따옴표·공백 같은 쓰레기만
막는다), 소문자로 맞춰 둔다 — 응답의 조직 헤더도 같은 정규화(`normalize_account`) 뒤 비교한다. 오류 문장에는 항목 번호와
규칙만 싣고 값은 싣지 않는다(기동 로그·Bugsink 로 가는 문장에 조직 id 를 남길 이유가 없다).

이 모듈은 아무 `api` 모듈도 import 하지 않는다 — 설정(`core/config.py`)이 기동 검증에서 이 파서를 부른다.
"""

import re
from typing import Literal

AccountProvider = Literal["anthropic", "aws"]

_ANTHROPIC_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_AWS_ID = re.compile(r"[0-9]{12}")


def normalize_account(value: str | None) -> str | None:
    """조직 id 비교용 정규화(앞뒤 공백 제거·소문자). 비면 `None`."""
    if value is None:
        return None
    return value.strip().lower() or None


def parse_allowed_accounts(raw: str) -> frozenset[tuple[AccountProvider, str]]:
    """허용 목록 문자열을 (공급자, id) 집합으로 읽는다. 형식이 틀리면 `ValueError`(메시지에 값은 넣지 않는다)."""
    accounts: set[tuple[AccountProvider, str]] = set()
    for number, item in enumerate(raw.split(","), start=1):
        entry = item.strip()
        if not entry:
            continue
        token, sep, value = entry.partition(":")
        if not sep:
            raise ValueError(f"entry #{number}: expected 'provider:id'")
        account: tuple[AccountProvider, str]
        if token == "anthropic":
            if not _ANTHROPIC_ID.fullmatch(value):
                raise ValueError(f"entry #{number}: anthropic id must be 1-64 characters of [A-Za-z0-9_-]")
            account = ("anthropic", value.lower())
        elif token == "aws":
            if not _AWS_ID.fullmatch(value):
                raise ValueError(f"entry #{number}: aws id must be 12 digits")
            account = ("aws", value)
        else:
            raise ValueError(f"entry #{number}: provider must be 'anthropic' or 'aws'")
        if account in accounts:
            raise ValueError(f"entry #{number}: duplicated")
        accounts.add(account)
    return frozenset(accounts)
