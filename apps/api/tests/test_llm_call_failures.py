"""소설 작업의 모델 호출 실패를 실패 사유 코드로 가르는 헬퍼와, 그 헬퍼를 채팅·기억 경로가 쓰지 않는다는 고정.

실패 경고 로그의 글(원인 종류·상태·요청 id)은 `test_novelize_runner.py` 의 호출 실패 로그 시험이 실행 경로째 본다."""

import ast
from pathlib import Path

import pytest

from api.llm.call_failures import LLMFailureCode, classify_llm_failure
from api.llm.client import (
    LLMClientError,
    LLMEmptyResponseError,
    LLMPolicyViolationError,
    LLMRateLimitError,
    LLMTruncatedError,
)


class _TruncatedAndBlockedError(LLMTruncatedError, LLMPolicyViolationError):
    """두 하위 예외를 함께 가진 예외 — 어느 쪽을 먼저 보는지 드러낸다."""


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        pytest.param(LLMTruncatedError("잘림"), "truncated", id="truncated"),
        pytest.param(LLMEmptyResponseError("빈 본문"), "empty", id="empty"),
        pytest.param(LLMPolicyViolationError("차단"), "blocked", id="blocked"),
        pytest.param(LLMRateLimitError("쿼터"), "llm_error", id="rate_limit"),
        pytest.param(LLMClientError("실패"), "llm_error", id="plain"),
        pytest.param(_TruncatedAndBlockedError("둘 다"), "truncated", id="truncated-before-blocked"),
    ],
)
def test_a_failed_call_maps_to_its_failure_code(error: LLMClientError, expected: LLMFailureCode) -> None:
    """잘림·빈 본문·안전 차단은 제 사유로, 나머지(쿼터 소진 포함)는 호출 실패로 가른다. 하위 예외를 잘림 → 빈 본문 → 차단 순으로
    본다. 깨지는 시나리오: 사유를 잘못 갈라 사용자에게 "다시 시도" 대신 "차단" 안내가 가거나, 쿼터 소진이 따로 갈라져 화면이
    모르는 사유 코드가 저장된다."""
    assert classify_llm_failure(error) == expected


_HELPER = "api.llm.call_failures"


def _imports_helper(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(alias.name == _HELPER for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom):
            if node.module == _HELPER:
                return True
            if node.module == "api.llm" and any(alias.name == "call_failures" for alias in node.names):
                return True
    return False


def test_the_import_check_sees_every_way_of_importing_the_helper() -> None:
    """아래 고정이 헛돌지 않는지 — 세 가지 import 꼴을 모두 잡고 다른 모듈 import 는 잡지 않는다."""
    assert _imports_helper("from api.llm.call_failures import classify_llm_failure")
    assert _imports_helper("from api.llm import call_failures")
    assert _imports_helper("import api.llm.call_failures")
    assert not _imports_helper("from api.llm.client import LLMClientError")
    assert not _imports_helper("from api.llm import client")


def test_chat_and_memory_code_does_not_import_the_novel_failure_helper() -> None:
    """채팅과 기억 추출(모두 `api/chat/` 아래)은 이 헬퍼를 쓰지 않는다 — 소설 작업의 실패 갈래를 고치는 변경이 채팅 턴·기억
    추출의 실패 처리를 함께 움직이지 않게 묶어 둔다. 깨지는 시나리오: 채팅 경로가 이 헬퍼를 가져다 써, 소설 쪽 사유 코드 변경이
    채팅 오류 안내까지 바꾼다."""
    chat_dir = Path(__file__).resolve().parents[1] / "src" / "api" / "chat"
    sources = sorted(chat_dir.rglob("*.py"))
    assert sources
    assert [path.name for path in sources if _imports_helper(path.read_text(encoding="utf-8"))] == []
