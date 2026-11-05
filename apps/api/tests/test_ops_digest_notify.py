"""일일 운영 요약의 호스트 알림 스크립트(`scripts/ops/daily_digest_notify.py`)와 앱 출력의 맞물림.

알림 스크립트는 VM 의 시스템 python3 로 돌아 앱 패키지를 import 할 수 없어 머리 문자열의 사본을 갖는다 — 그 사본이 앱 상수와
같은지, 앱이 낸 출력을 그대로 넣으면 통마다 하나씩 나뉘어 보내지는지 여기서 본다.
"""

import io
from datetime import date

import pytest

from api.llm.usage_store import UsageRow
from api.ops_digest import report
from api.ops_digest.watch import WatchMetrics
from ops import daily_digest_notify


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    messages: list[str] = []

    def _record(message: str) -> bool:
        messages.append(message)
        return False

    monkeypatch.setattr(daily_digest_notify, "notify", _record)
    return messages


def _rendered(*, dry_run: bool) -> str:
    """두 통 이상으로 나뉘는 요약 — LLM 줄이 꽉 차고 감시 조건이 모두 충족된 날."""
    digest = report.Digest(
        day=date(2026, 10, 21),
        real=report.Group(),
        internal=report.Group(),
        pending=report.Pending(
            reports={"작품": 0},
            inquiries=0,
            appeals=0,
            novel_first_reviews=0,
            refunds_in_progress=0,
            manual_payments=0,
            payout_applications=0,
        ),
        llm=[
            UsageRow(day=None, call_site=f"call_site_{n:02d}", model="gemini-3.5-flash-lite", calls=1, prompt=10)
            for n in range(30)
        ],
        watch=WatchMetrics(**dict.fromkeys(WatchMetrics.__dataclass_fields__, 10_000)),
    )
    return report.render(digest, dry_run=dry_run)


def test_the_header_copy_matches_the_app_constant() -> None:
    assert daily_digest_notify.MESSAGE_HEADER == report.MESSAGE_HEADER


def test_stdin_is_sent_one_message_per_header_in_order(monkeypatch: pytest.MonkeyPatch, sent: list[str]) -> None:
    rendered = _rendered(dry_run=False)
    monkeypatch.setattr("sys.stdin", io.StringIO("compose 경고 한 줄\n" + rendered + "\n"))

    assert daily_digest_notify.main([]) == 0

    assert len(sent) > 1
    assert all(message.startswith(report.MESSAGE_HEADER) for message in sent)
    assert all(len(message) <= 2_000 for message in sent)
    # 머리 앞의 줄은 버리고, 나머지는 한 줄도 잃지 않는다.
    assert "\n\n".join(sent) == rendered


def test_dry_run_output_sends_nothing(monkeypatch: pytest.MonkeyPatch, sent: list[str]) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(_rendered(dry_run=True)))

    assert daily_digest_notify.main([]) == 0

    assert sent == []


def test_arguments_are_sent_as_one_fixed_message(sent: list[str]) -> None:
    assert daily_digest_notify.main(["📊 일일 운영 요약 실패(종료 코드 1)", "— 로그 확인"]) == 0
    assert daily_digest_notify.main(["  "]) == 0

    assert sent == ["📊 일일 운영 요약 실패(종료 코드 1) — 로그 확인"]
