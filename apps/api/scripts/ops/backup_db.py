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
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from ops.db_url import describe, to_libpq_url
from ops.pg import run_sh

AWS_IMAGE = "amazon/aws-cli:latest"
DAILY_KEEP = 7
WEEKLY_KEEP = 4

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path("backups"))
    parser.add_argument("--no-upload", action="store_true", help="덤프만 뜨고 R2 는 건너뛴다")
    parser.add_argument("--keep-local", action="store_true", help="업로드 후에도 로컬 파일을 남긴다")
    args = parser.parse_args()

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

    if not args.keep_local:
        target.unlink()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, KeyError) as error:
        print(f"실패: {error}", file=sys.stderr)
        sys.exit(1)
