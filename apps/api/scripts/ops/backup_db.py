"""Postgres 덤프를 뜨고 R2 에 올린다. 이전과 무관하게 상시 운영으로 남는 스크립트다.

    # 프로덕션(Neon) 덤프만 — 업로드 없이
    cd apps/api && PYTHONPATH=scripts uv run --env-file ~/.config/ddona/prod.env \\
        python -m ops.backup_db --out-dir ~/backups --no-upload

    # VM 크론 (덤프 → R2 업로드 → 오래된 것 정리)
    cd /opt/ddona/app/apps/api && PYTHONPATH=scripts python -m ops.backup_db

**덤프 옵션이 `-Fc --no-owner --no-acl` 인 이유.** custom 포맷(`-Fc`)은 선택·병렬 복원이 되고,
복원 대상(VM 의 PG)은 롤 이름이 Neon 과 달라 소유자·권한 구문이 들어가면 복원 중 에러가 쏟아진다.

**보관 정책은 R2 수명주기 규칙이 아니라 여기서 판단한다.** 수명주기는 "N일 지나면 삭제"밖에 못
하는데 우리가 원하는 건 "일단위 7개 + 주단위 4개"라 갯수 기준이기 때문이다.

⚠️ **백업은 자산과 같은 버킷(`ai-chracter-chat`)의 `backup/` 아래 산다.** 전용 버킷을 따로 두려
했지만 기존 R2 토큰이 그 버킷에만 스코프돼 있어(다른 버킷은 전부 403) 새 토큰 없이는 쓸 수 없었다.
같은 버킷을 쓰는 대가는 하나뿐이다 — **`prune`이 자산을 지울 수 있는 거리에 있다.** 그래서
삭제 대상을 백업 파일명 패턴(`BACKUP_NAME`)에 **정확히** 맞는 이름으로 제한한다. 프리픽스를
어떻게 잘못 넘겨도 `assets/…` 키에는 닿지 않는다.

(자산이 브라우저에 노출되는 문제는 없다 — R2의 CORS는 읽기 권한을 주지 않고, S3 엔드포인트는
항상 SigV4 서명을 요구한다. 공개 접근은 별도 `r2.dev` 도메인을 켜야 생기는데 켜져 있지 않다.)

**백업(덤프+업로드+prune)이 전부 성공한 뒤에만 만료된 `withdrawn_emails` 행도 지운다**
(legal-revision-goal-prompt.md LR-32). 처리방침 제4조 2항·약관 제14조 4항이 약속한 "1년간
보관하고 그 기간이 지나면 파기합니다"를 실제로 수행하는 유일한 코드다 — `auth/router.py`의
`_reregistration_blocked`는 조회 시 만료를 무시할 뿐 행을 지우지 않는다. 삭제를 백업 뒤에
두는 이유는 지우기 전 상태를 그날 백업에 남기기 위해서다. `--no-upload`(로컬 전용 덤프)
경로에는 얹지 않는다 — 그 경로는 durable 백업을 남기지 않는다.

⚠️ **이 파일은 SQLAlchemy/asyncpg/`api.*`를 import 하면 안 된다.** 프로덕션 크론은
`/opt/ddona/backup.sh`(VM 실측)가 `PYTHONPATH=/opt/ddona/scripts` 아래 시스템
`/usr/bin/python3 -m ops.backup_db`로 돌리는데, 그 경로엔 `api` 패키지가 없고 그 python3엔
SQLAlchemy/asyncpg가 안 깔려 있다(boto3만 있다). S5-d가 만료 `withdrawn_emails` 삭제를
SQLAlchemy로 구현해 배포했다가 매일 18:00 UTC 크론이 import 시점에 죽어 백업이 통째로
멈췄다(S5-e에서 되돌림) — 그래서 삭제도 `pg_dump`와 같은 방식(`run_sh`로 컨테이너 안
`psql`을 부름)으로 한다. `tests/test_ops_production_cron_importable.py`가 이 제약을 `ast`로 고정한다.
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO

from ops.db_url import describe, to_libpq_url
from ops.notify import notify, ping
from ops.pg import run_sh, shell_quote

AWS_IMAGE = "amazon/aws-cli:latest"
DAILY_KEEP = 7
WEEKLY_KEEP = 4

# monitoring-techspec.md MT-12: R2 무료 한도(DEPLOY.md §1-1). 새 토큰·새 크론을 만들지 않고
# 이미 있는 `aws()`/prune 경로로 총 사용량을 재는 김에 임계값만 비교한다.
DEFAULT_R2_CAPACITY_THRESHOLD_BYTES = 10 * 1024**3

# legal-revision-goal-prompt.md LR-7·LR-32: `auth/router.py`의 `_reregistration_blocked`(조회)와
# 같은 1년을 써야 "차단이 풀리는 시점"과 "행이 파기되는 시점"이 갈라지지 않는다. 원본은
# `api.core.constants.WITHDRAWN_EMAIL_BLOCK_PERIOD`지만 VM에 `api` 패키지가 없어 이 파일에서는
# import 할 수 없다(위 경고 참고) — 그래서 로컬로 값을 복제하고,
# `tests/test_ops_backup_withdrawn_emails.py::test_block_period_matches_api_constant`가 두 값이
# 갈라지지 않는지 매 실행마다 확인한다(그 테스트는 일반 pytest 환경에서 돌아 `api`를 볼 수 있다).
WITHDRAWN_EMAIL_BLOCK_PERIOD = timedelta(days=365)

# 백업 파일명은 UTC 타임스탬프 하나뿐이다(`20260902T070331Z.dump`). 삭제는 이 형태에 정확히
# 맞는 이름에만 허용되며, 그게 자산과 버킷을 공유해도 안전한 이유다.
BACKUP_NAME = re.compile(r"^\d{8}T\d{6}Z\.dump$")

# 자산(`assets/`)과 갈라놓는 최상위 프리픽스. 전용 버킷을 쓰게 되면 빈 값으로 덮으면 된다.
DEFAULT_PREFIX = "backup/"


def dump(url: str, target: Path) -> None:
    """`pg_dump -Fc` 결과를 그대로 파일로 받는다."""
    with target.open("wb") as handle:
        result = run_sh('pg_dump -Fc --no-owner --no-acl "$PGURL"', url=url, stdout=handle)
    if result.returncode != 0:
        target.unlink(missing_ok=True)  # 반쪽짜리 덤프를 남기지 않는다 — 있으면 성공으로 오인된다.
        raise RuntimeError(f"pg_dump 실패:\n{result.stderr.decode().strip()}")


def aws(
    args: list[str], *, stdin: int | IO[bytes] = subprocess.DEVNULL
) -> subprocess.CompletedProcess[bytes]:
    """R2(S3 호환)에 대고 aws-cli 를 도커로 돌린다. 자격증명은 `-e` 로 이름만 넘긴다."""
    return subprocess.run(
        [
            "docker", "run", "--rm", "--interactive",
            "-e", "AWS_ACCESS_KEY_ID", "-e", "AWS_SECRET_ACCESS_KEY", "-e", "AWS_DEFAULT_REGION",
            AWS_IMAGE, "--endpoint-url", os.environ["S3_ENDPOINT_URL"], *args,
        ],
        env={**os.environ, "AWS_DEFAULT_REGION": os.environ.get("AWS_REGION", "auto")},
        stdin=stdin,
        capture_output=True,
    )


def upload(local: Path, bucket: str, key: str) -> None:
    """로컬 덤프를 stdin 으로 흘려보낸다 — 컨테이너에 볼륨을 붙이지 않아도 된다."""
    with local.open("rb") as handle:
        result = aws(["s3", "cp", "-", f"s3://{bucket}/{key}"], stdin=handle)
    if result.returncode != 0:
        raise RuntimeError(f"업로드 실패:\n{result.stderr.decode().strip()}")


def parse_listing(text: str) -> list[str]:
    """`s3 ls` 출력에서 **백업 파일 이름만** 골라 시간순으로 돌려준다.

    이 함수가 `prune` 의 안전장치다. 백업과 자산이 한 버킷에 살기 때문에, 삭제 후보는 반드시
    백업 파일명 형태여야 한다 — 하위 디렉터리 줄(`PRE assets/`)이나 자산 키는 여기서 전부 걸러진다.
    이름이 UTC 타임스탬프뿐이라 사전순 정렬이 곧 시간순 정렬이다.
    """
    names = []
    for line in text.splitlines():
        if not line.strip():
            continue
        name = line.split()[-1]
        if BACKUP_NAME.match(name):
            names.append(name)
    return sorted(names)


def prune(bucket: str, prefix: str, keep: int) -> list[str]:
    """`prefix` 아래에서 최신 `keep` 개만 남기고 지운다. 지운 키 목록을 돌려준다."""
    if not prefix.endswith("/"):
        raise RuntimeError(f"프리픽스는 '/' 로 끝나야 한다(자산 키에 닿지 않도록): {prefix!r}")

    listing = aws(["s3", "ls", f"s3://{bucket}/{prefix}"])
    if listing.returncode != 0:
        # `aws s3 ls` 는 **객체가 하나도 없는 프리픽스**에도 exit 1 을 낸다 — 단, 그때는 stderr 가
        # 비어 있다. 첫 실행(아직 weekly/ 가 없음)이 정확히 이 경우라 실패로 취급하면 안 된다.
        # 진짜 오류(권한·네트워크)는 stderr 에 메시지가 남으므로 그것만 터뜨린다.
        message = listing.stderr.decode().strip()
        if not message:
            return []
        raise RuntimeError(f"목록 조회 실패:\n{message}")

    names = parse_listing(listing.stdout.decode())
    doomed = names[:-keep] if keep < len(names) else []
    for name in doomed:
        result = aws(["s3", "rm", f"s3://{bucket}/{prefix}{name}"])
        if result.returncode != 0:
            raise RuntimeError(f"삭제 실패({name}):\n{result.stderr.decode().strip()}")
    return doomed


def parse_s3_summary(text: str) -> int:
    """`aws s3 ls --recursive --summarize` 출력에서 `Total Size:` 줄의 바이트 수를 읽는다.

    `Total Objects:` 줄도 `Total`로 시작하므로 접두어는 `Total Size:`까지 정확히 맞춰야 한다 —
    느슨하게 매칭하면 객체 개수를 바이트로 잘못 읽어 임계값과 전혀 다른 스케일로 비교하게 된다.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Total Size:"):
            return int(stripped.split(":", 1)[1].strip())
    raise ValueError("`aws s3 ls --summarize` 출력에 'Total Size:' 줄이 없다")


def check_r2_capacity(bucket: str) -> None:
    """`monitoring-techspec.md` MT-12: 버킷 전체 용량이 임계값을 넘을 때만 Discord로 알린다.

    새 스크립트·새 크론·새 Cloudflare 토큰을 만들지 않는다 — 이미 있는 `aws()` 헬퍼로 한 번 더
    호출할 뿐이다(Cloudflare GraphQL 대신인 이유는 techspec MT-12 참고: 현재 토큰에 Analytics
    권한이 없다).
    """
    listing = aws(["s3", "ls", f"s3://{bucket}/", "--recursive", "--summarize"])
    if listing.returncode != 0:
        # `prune()`과 같은 함정 — 객체가 하나도 없는 버킷도 exit 1을 내지만 그때는 stderr가
        # 비어 있다. 진짜 오류(권한·네트워크)만 stderr에 메시지가 남으므로 그것만 터뜨린다.
        message = listing.stderr.decode().strip()
        if not message:
            return
        raise RuntimeError(f"용량 조회 실패:\n{message}")

    total_bytes = parse_s3_summary(listing.stdout.decode())

    raw_threshold = os.environ.get("R2_CAPACITY_THRESHOLD_BYTES")
    try:
        threshold = int(raw_threshold) if raw_threshold is not None else DEFAULT_R2_CAPACITY_THRESHOLD_BYTES
    except ValueError as error:
        # ValueError를 그대로 두면 `__main__`의 좁은 `except (RuntimeError, KeyError)` 밖으로
        # 새 나가 실패 ping도 못 보낸다(MT-11) — 이 파일의 다른 설정 오류(KeyError)와 같은
        # 급으로 다루도록 RuntimeError로 갈아 끼운다.
        raise RuntimeError(f"R2_CAPACITY_THRESHOLD_BYTES 값이 잘못됐다: {raw_threshold!r}") from error

    if total_bytes >= threshold:
        used_gb = total_bytes / 1024**3
        threshold_gb = threshold / 1024**3
        notify(f"⚠️ R2 사용량 {used_gb:.2f}GB — 임계값 {threshold_gb:.2f}GB 초과")


def delete_expired_withdrawn_emails(url: str, *, now: datetime) -> int:
    """legal-revision-goal-prompt.md LR-32: `withdrawn_at + WITHDRAWN_EMAIL_BLOCK_PERIOD`가
    지난 `withdrawn_emails` 행을 지우고 지운 개수를 돌려준다. 처리방침 제4조 2항·약관 제14조
    4항이 "1년이 지나면 파기합니다"라고 약속하는 대상이 바로 이 행이다.

    `dump()`와 같은 방식(`run_sh`로 컨테이너 안 `psql`을 부름)을 쓴다 — 위 파일 상단 경고 참고,
    이 파일은 SQLAlchemy를 import 할 수 없다. 삭제 건수는 `.rowcount`(SQLAlchemy 전용) 대신
    `DELETE ... RETURNING`이 `psql -At`로 찍는 줄 수로 센다(`admin/users.py`가 `.returning()`을
    쓰는 이유와 같다 — 여기선 아예 `.rowcount` 자체가 없다). 각 줄이 지워진 행 하나의
    `email_hmac`이므로 빈 줄만 제외하면 그대로 개수다.
    """
    cutoff = now - WITHDRAWN_EMAIL_BLOCK_PERIOD
    sql = (
        f"DELETE FROM withdrawn_emails WHERE withdrawn_at < '{cutoff.isoformat()}' "
        "RETURNING email_hmac;"
    )
    result = run_sh(f'psql "$PGURL" -At -c {shell_quote(sql)}', url=url, stdout=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"만료 삭제 실패:\n{result.stderr.decode().strip()}")
    return len([line for line in result.stdout.decode().splitlines() if line.strip()])


def _healthcheck(suffix: str = "") -> None:
    """monitoring-techspec.md MT-11: healthchecks.io check-in.

    healthchecks.io 관례대로 base URL에 접미사를 붙여 start(`/start`)·성공(빈 접미사)·
    실패(`/fail`)를 구분한다. `HEALTHCHECKS_BACKUP_PING_URL`이 없으면(알림 미설정) 아무 일도
    하지 않는다 — `ops.notify.ping` 자체도 예외를 던지지 않으므로 이 호출이 백업을 막는 일은
    없다.
    """
    base = os.environ.get("HEALTHCHECKS_BACKUP_PING_URL")
    if base:
        ping(f"{base}{suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path("backups"))
    parser.add_argument("--no-upload", action="store_true", help="덤프만 뜨고 R2 는 건너뛴다")
    parser.add_argument("--keep-local", action="store_true", help="업로드 후에도 로컬 파일을 남긴다")
    args = parser.parse_args()

    _healthcheck("/start")  # MT-11: "예정 시각에 안 돌았음"을 잡으려면 시작부터 찍어야 한다.

    url = to_libpq_url(os.environ["DATABASE_URL"])
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    target = args.out_dir / f"{stamp}.dump"

    print(f"▶ 덤프: {describe(url)} → {target}")
    dump(url, target)
    size_mb = target.stat().st_size / 1024 / 1024
    print(f"  {size_mb:.2f} MB")

    if args.no_upload:
        print("↷ 업로드 건너뜀(--no-upload)")
        # ⚠️ MT-11: 여기서 성공 ping을 보내지 않는다 — 크론은 이 플래그를 쓰지 않으므로, 보내면
        # 실제로는 R2에 아무것도 안 올라간 로컬 전용 실행이 healthchecks.io에는 "오늘 백업
        # 성공"으로 찍힌다.
        return 0

    # 백업 버킷을 따로 안 주면 자산 버킷(`S3_BUCKET_NAME`)을 쓴다 — 기존 토큰이 그 버킷 전용이라
    # 새 토큰 없이 돌아가게 하기 위한 기본값이다. `backup/` 프리픽스가 자산과 갈라놓는다.
    bucket = os.environ.get("BACKUP_BUCKET_NAME") or os.environ["S3_BUCKET_NAME"]
    base = os.environ.get("BACKUP_PREFIX", DEFAULT_PREFIX)

    # 주단위 사본은 일요일에만. 일단위와 같은 파일을 두 키에 올리므로 복원 절차는 하나로 같다.
    kinds = ["daily/"] + (["weekly/"] if datetime.now(UTC).weekday() == 6 else [])
    for kind in kinds:
        upload(target, bucket, f"{base}{kind}{target.name}")
        print(f"↑ s3://{bucket}/{base}{kind}{target.name}")

    for kind, keep in (("daily/", DAILY_KEEP), ("weekly/", WEEKLY_KEEP)):
        removed = prune(bucket, f"{base}{kind}", keep)
        if removed:
            print(f"🗑 {base}{kind} 정리: {len(removed)}개 삭제 ({', '.join(removed)})")

    check_r2_capacity(bucket)  # MT-12: prune 직후 총 용량을 재서 임계 초과일 때만 알린다.

    # legal-revision-goal-prompt.md LR-32: 여기 도달했다는 것 자체가 덤프·업로드·prune이 전부
    # 성공했다는 뜻이다 — 앞선 어느 단계든 실패하면 예외가 여기까지 오기 전에 전파되어 삭제도
    # 함께 건너뛴다. 순서 고정: 백업 뒤에 지워야 지우기 전 상태가 오늘 백업에 남는다.
    expired_count = delete_expired_withdrawn_emails(url, now=datetime.now(UTC))
    if expired_count:
        print(f"🗑 withdrawn_emails 만료 정리: {expired_count}개 삭제")

    if not args.keep_local:
        target.unlink()

    _healthcheck()  # MT-11: 성공 신호. 접미사 없음이 healthchecks.io의 "성공" 규약이다.
    return 0


def _on_failure(error: Exception) -> int:
    """`__main__`이 잡은 예외를 stderr에 남기고 실패 ping을 보낸다. 반환값은 그대로 exit code다.

    MT-11: 아래 `except (RuntimeError, KeyError)` **밖**의 예외(예: docker 미기동으로 인한
    `FileNotFoundError`)는 여기 도달하지 못해 실패 ping도 나가지 않는다 — 그 경우는 start ping
    이후 healthchecks.io 자체의 grace time 초과 감지가 대신 잡는다(두 경로가 서로를 덮는다).
    이 except를 넓히지 않는 이유: 원래 이 가드는 "사전에 식별한 실패 모드"만 좁게 잡도록
    설계돼 있다(S5-d/S5-e 회귀 — 예상 못한 예외까지 뭉뚱그려 삼키면 새 버그 클래스를 조용히
    숨긴다) — 이 설계를 MT-11 때문에 흔들지 않는다.
    """
    print(f"실패: {error}", file=sys.stderr)
    _healthcheck("/fail")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, KeyError) as error:
        sys.exit(_on_failure(error))
