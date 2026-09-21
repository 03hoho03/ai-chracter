"""`ops/expire_clover.py` — clover-page-goal-prompt.md CE-7~CE-9: 출석·미션 클로버 만료 배치.

`test_ops_purge_image_requests.py`(같은 `run_sh` 경계 모킹 패턴)를 그대로 베꼈다. Postgres가
실제로 이 SQL을 원자적으로 실행하는지는 이 스위트가 검증하지 않는다 — `run_sh`가 매번 진짜
도커+psql을 부르므로 워크트리마다 다른 도커 네트워크 구성에 이식 가능한 단위 테스트로 못
박을 수 없다(`test_ops_backup_withdrawn_emails.py`와 같은 이유). 실 DB 검증은
`clover-page-goal-prompt.md` §5-3이 요구하는 별도의 로컬 실측(진행 문서에 결과를 남긴다)이 맡는다.
이 파일은 (1) cutoff가 두 SQL 문장에 같은 값으로 들어가는지 (2) CE-9가 확정한 세 지점(`OLD.
remaining`·`deducted` CTE에서 잔액 직접 수신·락 순서 users→clover_lots)이 SQL 텍스트에 실제로
있는지 (3) `RETURNING` 출력 줄 수 세기 (4) 실패 시 예외 전파·Discord 알림 배선만 확인한다.
"""

import subprocess
from datetime import UTC, datetime

import pytest

import ops.expire_clover as expire_clover


# ── T-4: cutoff·원자성(한 트랜잭션) ─────────────────────────────────────────────
def test_same_cutoff_is_used_in_both_statements(monkeypatch: pytest.MonkeyPatch) -> None:
    """CE-9 — `cutoff`는 스크립트 시작 시각에 한 번 계산해 두 문장에 같은 값을 넘긴다.

    깨지는 시나리오: 두 문장이 각자 `now()`를 다시 부르면(또는 서로 다른 `cutoff` 값을 쓰면)
    문장 사이에 로트가 새로 만료로 넘어가 1단계에서 안 잠긴 유저가 2단계에 끼어들 수 있다.
    """
    now = datetime(2026, 9, 28, 0, 0, 0, tzinfo=UTC)
    captured: dict[str, str] = {}

    def _fake(
        script: str, *, url: str, stdin: object = None, stdout: object = None
    ) -> subprocess.CompletedProcess[bytes]:
        captured["script"] = script
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(expire_clover, "run_sh", _fake)

    expire_clover.expire_clover_lots("postgresql://unused", cutoff=now)

    assert captured["script"].count(now.isoformat()) == 2


def test_whole_script_is_one_run_sh_call_wrapped_in_begin_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-4 — CTE가 원자적이려면 두 SQL 문장이 **하나의 `run_sh` 호출**(하나의 psql 세션)
    안에서 `BEGIN`~`COMMIT`으로 묶여야 한다.

    깨지는 시나리오: 구현이 1단계·2단계를 각각 별도 `run_sh` 호출로 나누면(별도 psql 세션 =
    별도 트랜잭션), 첫 호출이 성공하고 두 번째가 실패했을 때 로트만 0이 되고 잔액은 그대로
    남는 부분 반영이 가능해진다.
    """
    call_count = 0
    captured_script = ""

    def _fake(
        script: str, *, url: str, stdin: object = None, stdout: object = None
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal call_count, captured_script
        call_count += 1
        captured_script = script
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(expire_clover, "run_sh", _fake)

    expire_clover.expire_clover_lots("postgresql://unused", cutoff=datetime.now(UTC))

    assert call_count == 1
    assert "BEGIN;" in captured_script
    assert "COMMIT;" in captured_script


# ── T-4 확정 사항 1: `OLD.remaining` ────────────────────────────────────────────
def test_burned_amount_reads_old_remaining_not_the_post_update_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 CE-9 확정 사항 1 — `RETURNING`이 `OLD.remaining`이 아니라 그냥 `remaining`(갱신 **후**
    값)이면 `UPDATE ... SET remaining = 0`이 이미 적용된 뒤라 소멸량이 **항상 0**으로 찍힌다.

    깨지는 시나리오: `OLD.remaining`을 `remaining`으로 되돌리면 이 단언이 깨진다 — 정확히
    이전 스케치에 있던 버그(goal-prompt CE-9)다.
    """
    captured: dict[str, str] = {}

    def _fake(
        script: str, *, url: str, stdin: object = None, stdout: object = None
    ) -> subprocess.CompletedProcess[bytes]:
        captured["script"] = script
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(expire_clover, "run_sh", _fake)

    expire_clover.expire_clover_lots("postgresql://unused", cutoff=datetime.now(UTC))

    assert "RETURNING user_id, OLD.remaining AS burned" in captured["script"]


# ── T-4 확정 사항 2: `deducted` CTE에서 잔액을 직접 받는다 ──────────────────────
def test_final_insert_reads_balance_after_from_the_deducted_cte_not_a_users_rejoin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 CE-9 확정 사항 2 — 마지막 INSERT가 `users`를 다시 JOIN해 `clover_balance`를 읽으면
    CTE는 문장 시작 시점 스냅샷이라 차감 **전** 잔액이 찍힌다. `deducted` CTE 자신의
    `RETURNING`에서 갱신 후 잔액(`balance_after`)을 직접 받아야 한다.

    깨지는 시나리오: 마지막 `INSERT ... SELECT`가 `deducted`가 아니라 `users`를 다시 JOIN하면
    `balance_after`가 차감 전 값이 된다 — 이전 스케치에 있던 버그 2(goal-prompt CE-9)다.
    """
    captured: dict[str, str] = {}

    def _fake(
        script: str, *, url: str, stdin: object = None, stdout: object = None
    ) -> subprocess.CompletedProcess[bytes]:
        captured["script"] = script
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(expire_clover, "run_sh", _fake)

    expire_clover.expire_clover_lots("postgresql://unused", cutoff=datetime.now(UTC))

    script = captured["script"]
    # `shell_quote`가 SQL 안의 작은따옴표를 이스케이프해 원문 그대로는 안 남는다(`'expire_burn'`
    # 류) — 구성요소별로 확인한다(`test_ops_purge_image_requests.py`와 같은 이유).
    assert "RETURNING u.id AS user_id, u.clover_balance AS balance_after, b.total AS total" in script
    assert "SELECT gen_random_uuid(), user_id, -total, balance_after," in script
    assert "expire_burn" in script
    assert "  FROM deducted" in script
    # `users`는 1단계 잠금과 `deducted`의 자기 UPDATE에서만 나온다 — 재조회용 JOIN이 없다.
    assert "JOIN users" not in script


# ── T-4 확정 사항 3 / T-12: 락 순서 users → clover_lots ─────────────────────────
def test_lock_order_is_users_first_then_clover_lots(monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 CE-9 확정 사항 3(T-12) — 락 순서가 CE-6(차감 경로)과 같아야 한다: `users`를 먼저
    `FOR UPDATE`로 잠그고, 그 다음에야 `clover_lots`를 갱신한다. 반대로 잡으면(로트를 먼저
    잠그고 유저를 나중에 잠그면) 배치와 동시 차감(`core/clover.py`의 `_apply`, users→
    clover_lots 순서)이 겹칠 때 재현 가능한 데드락이다.

    🔴 T-12 — 진짜 동시 실행으로 데드락을 재현하지는 않는다(생산 경로가 `psql`을 도커로 띄우는
    `run_sh` 뒤에 있어 이 스위트가 매번 실제 도커+psql을 부르게 되고, 워크트리마다 다른 도커
    네트워크 구성에 이식 가능한 단위 테스트로 못 박을 수 없다 — 이 파일 docstring, 그리고
    `test_ops_backup_withdrawn_emails.py`가 같은 이유로 실제 필터링을 검증하지 않는 것과 같은
    제약). 대신 **락 획득 순서를 관찰**한다 — `psql -c "stmt1; stmt2; ..."`은 한 세션 안에서
    문장을 반드시 순서대로 실행하므로, 생성된 SQL 텍스트에서 `users ... FOR UPDATE`가
    `UPDATE clover_lots`보다 앞에 있다는 것이 곧 실제 락 획득 순서다.

    깨지는 시나리오: 두 블록의 순서가 뒤집히면(로트를 먼저 잠그면) 이 텍스트 순서 단언이
    깨진다.
    """
    captured: dict[str, str] = {}

    def _fake(
        script: str, *, url: str, stdin: object = None, stdout: object = None
    ) -> subprocess.CompletedProcess[bytes]:
        captured["script"] = script
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(expire_clover, "run_sh", _fake)

    expire_clover.expire_clover_lots("postgresql://unused", cutoff=datetime.now(UTC))

    script = captured["script"]
    users_lock_index = script.index("FOR UPDATE")
    lots_update_index = script.index("UPDATE clover_lots")
    assert users_lock_index < lots_update_index


# ── RETURNING 출력 줄 수 세기 ────────────────────────────────────────────────────
def test_affected_count_comes_from_the_locking_selects_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`expire_clover_lots`의 반환값은 1단계(잠금) `SELECT`가 찍는 줄 수다 — 2단계
    (`WITH...INSERT`)는 top-level `RETURNING`이 없어 `-q`가 명령 태그까지 지운다(goal-prompt
    CE-9 원문 그대로, 트레일링 `RETURNING`을 추가하지 않았다).

    깨지는 시나리오: `-q`가 빠지면 `INSERT 0 n` 명령 태그가 한 줄 더 섞여 카운트가 부풀거나,
    빈 줄이 카운트에 섞여 0건일 때도 양수가 된다.
    """
    def _fake(
        script: str, *, url: str, stdin: object = None, stdout: object = None
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"user-a\nuser-b\n", stderr=b""
        )

    monkeypatch.setattr(expire_clover, "run_sh", _fake)

    affected = expire_clover.expire_clover_lots("postgresql://unused", cutoff=datetime.now(UTC))

    assert affected == 2


def test_missing_dash_q_would_overcount_by_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """깨지는 시나리오: `-Atq`에서 `-q`가 빠지면 명령 태그가 한 줄 더 찍혀 0건을 처리해도
    1건으로 센다(`backup_db.py`의 프로덕션 실측 회귀와 동일)."""
    captured: dict[str, str] = {}

    def _fake(
        script: str, *, url: str, stdin: object = None, stdout: object = None
    ) -> subprocess.CompletedProcess[bytes]:
        captured["script"] = script
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(expire_clover, "run_sh", _fake)

    affected = expire_clover.expire_clover_lots("postgresql://unused", cutoff=datetime.now(UTC))

    assert affected == 0
    assert " -Atq " in captured["script"]


# ── S5 적대적 리뷰(review-S5.md) 중요 1건: 부분 실패의 종료 코드 ──────────────────
def test_psql_is_invoked_with_on_error_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 review-S5.md §7 — `BEGIN;...COMMIT;`을 한 `-c` 인자로 보내는 다중 문장 스크립트는
    `-v ON_ERROR_STOP=1` 없이 돌리면 중간 문장이 실패해도 psql이 0을 반환할 수 있다고
    문서만으로는 단정할 수 없는 함정이다(리뷰가 지적).

    🔴 **실측(2026-09-21, 로컬 dev DB `ai_character_chat`, `postgres:18-alpine` psql
    클라이언트, `PG_DOCKER_NETWORK=ai-character-chat-dev_default`)**: `-v ON_ERROR_STOP=1`
    없이 이 파일과 같은 형태(`BEGIN; 성공 SELECT; 실패하는 UPDATE(CHECK 제약 위반);
    COMMIT;`)를 실행해도 이미 종료 코드 **1**이 나왔다(`-c` 인자 하나에 담긴 다중 문장이
    백엔드에 단일 쿼리 메시지로 전달돼, 중간 문장이 실패하면 이후 문장이 아예 실행되지 않고
    배치 전체가 롤백되기 때문 — Σ 불변식도 그대로 지켜졌다). 즉 "조용한 0 반환"은 이 코드
    형태·이 psql 버전에서는 재현되지 않았다.

    그래도 이 동작은 psql이 `-c` 다중 문장을 실제로 어떻게 배치하는지(문서화된 보장이
    아니라 관찰된 동작)에 기대고 있어, 버전이나 스크립트 형태가 바뀌면 달라질 수 있다 —
    CE-8이 전제하는 "배치 실행 여부 감지"가 여기 걸려 있으므로 실패 감지 의도를 명시적으로
    고정해 둔다.

    깨지는 시나리오: 이 플래그가 빠지면(또는 `-c` 뒤로 밀리면) 위 실측 결과가 우연이었던
    환경(다른 psql 버전 등)에서 부분 실패가 조용히 성공으로 읽혀 Discord 알림이 영원히
    안 뜬다.
    """
    captured: dict[str, str] = {}

    def _fake(
        script: str, *, url: str, stdin: object = None, stdout: object = None
    ) -> subprocess.CompletedProcess[bytes]:
        captured["script"] = script
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(expire_clover, "run_sh", _fake)

    expire_clover.expire_clover_lots("postgresql://unused", cutoff=datetime.now(UTC))

    script = captured["script"]
    assert " -v ON_ERROR_STOP=1 " in script
    assert script.index("-v ON_ERROR_STOP=1") < script.index(" -c ")


def test_raises_when_psql_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """깨지는 시나리오: `run_sh`가 실패(nonzero exit)했는데 예외로 전파하지 않으면, 만료
    처리가 실제로는 안 됐는데도 크론이 성공으로 남아 실패 알림도 나가지 않는다."""

    def _fake(
        script: str, *, url: str, stdin: object = None, stdout: object = None
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr="psql: 연결 실패".encode()
        )

    monkeypatch.setattr(expire_clover, "run_sh", _fake)

    with pytest.raises(RuntimeError, match="연결 실패"):
        expire_clover.expire_clover_lots("postgresql://unused", cutoff=datetime.now(UTC))


def test_on_failure_notifies_discord_and_returns_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """깨지는 시나리오: 실패 시 `notify()` 배선이 빠지면, 매일 도는 만료 배치가 조용히 죽어도
    아무도 몰라 CE-7의 "7일 유효기간" 약속이 조용히 어긋난다."""
    sent: list[str] = []

    def _fake_notify(message: str) -> bool:
        sent.append(message)
        return True

    monkeypatch.setattr(expire_clover, "notify", _fake_notify)

    exit_code = expire_clover._on_failure(RuntimeError("psql: 연결 실패"))

    assert exit_code == 1
    assert len(sent) == 1
    assert "연결 실패" in sent[0]


def test_main_propagates_exception_without_notifying(monkeypatch: pytest.MonkeyPatch) -> None:
    """깨지는 시나리오: `main()`이 실패를 삼키면(예: 넓은 `except`로 감싸면) `__main__`의
    `_on_failure` 알림 배선까지 도달하지 못해 실패가 완전히 조용해진다."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["expire_clover.py"])

    with pytest.raises(KeyError):
        expire_clover.main()
