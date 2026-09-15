"""S5-e 재발 방지 + `monitoring-techspec.md` MT-9: 프로덕션 크론이 시스템 python3로 직접 부르는
ops 모듈들이 실제로 그 환경에서 import 가능한지 고정한다.

**대상은 `backup_db.py`·`restore_db.py` 둘뿐이다.** VM 시스템 python3로 실제 불리는 건 이 둘이다
— `DEPLOY.md` §3-4가 복원 절차를 `PYTHONPATH=. python3 -m ops.restore_db`로 명시한다.
`snapshot_redis.py`·`compare_rows.py`는 독스트링이 `uv run`만 안내하고, `cloudrun_to_dotenv.py`는
`DEPLOY.md`가 "사문 — 실행 대상 없음"으로 선언한 죽은 코드라 셋 다 이 테스트의 범위 밖이다.

**허용 목록은 모듈별 dict다.** 공유 set이면 한 모듈 때문에 허용한 패키지를 다른 모듈이 몰래 써도
이 테스트가 잡지 못한다(예: `restore_db.py`가 `backup_db.py`용으로 열어 둔 `boto3`에 기대 import를
추가해도 통과해 버린다).

**근거(VM 실측, `/opt/ddona/backup.sh`)**:

    export PYTHONPATH=/opt/ddona/scripts
    exec /usr/bin/python3 -m ops.backup_db --out-dir /opt/ddona/backups

`/opt/ddona/scripts/`에는 `ops`만 있고 `api` 패키지가 없다. 그 시스템 `/usr/bin/python3`는
`boto3`는 있지만 `sqlalchemy`/`asyncpg`는 `ImportError`다. 크론은 `/etc/cron.d/ddona-backup`
(`0 18 * * * root /opt/ddona/backup.sh`)이 매일 18:00 UTC에 돌리고 `backup.sh`는
`set -euo pipefail` + `exec`라, 모듈 최상단 import 하나가 시스템에 없으면 그 즉시 크론 전체가
죽어 그날 백업이 통째로 사라진다 — S5-d가 `from sqlalchemy import delete` 등을 최상단에
추가해 실제로 이 사고를 냈다(S5-e에서 되돌림). `restore_db.py`는 복원 절차에서 같은 시스템
python3로 불리므로 같은 위험을 진다.

**`ast`를 쓰는 이유** — 정규식으로 import 문을 세다가 이 저장소가 `consent-gate` 런에서 두 번
틀린 선례가 있다. `ast.parse`로 모듈 최상단(top-level) `Import`/`ImportFrom` 노드만 보고,
함수/조건문 안의 지연 import는 보지 않는다 — 크론 기동 즉시 실패로 이어지는 건 최상단 import
뿐이기 때문이다.
"""

import ast
from pathlib import Path

import ops.backup_db as backup_db
import ops.restore_db as restore_db

# 모듈별 허용 목록. `ops`는 형제 모듈(`ops/pg.py`, `ops/db_url.py`)이라
# `PYTHONPATH=/opt/ddona/scripts`로 항상 잡힌다.
_ALLOWED_TOP_LEVEL_MODULES: dict[str, set[str]] = {
    # `boto3`는 VM 실측상 설치돼 있어 허용하지만, 이 파일이 실제로 그걸 쓰는 건 아니다
    # (R2 접근은 `docker run amazon/aws-cli`로 하지 파이썬 라이브러리로 하지 않는다) — 그래도
    # "쓸 수 있는 것"의 목록이므로 미리 열어 둔다.
    "backup_db": {
        "argparse",
        "os",
        "re",
        "subprocess",
        "sys",
        "datetime",
        "pathlib",
        "typing",
        "boto3",
        "ops",
    },
    "restore_db": {
        "argparse",
        "os",
        "sys",
        "pathlib",
        "ops",
    },
}


def _top_level_import_names(path: Path) -> set[str]:
    """모듈 최상단 `import`/`from ... import` 문에서 최상위 패키지 이름만 뽑는다."""
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module.split(".")[0])
    return names


def test_backup_db_top_level_imports_are_satisfied_by_production_cron_environment() -> None:
    path = Path(backup_db.__file__)
    imports = _top_level_import_names(path)

    disallowed = imports - _ALLOWED_TOP_LEVEL_MODULES["backup_db"]
    assert not disallowed, (
        f"ops/backup_db.py 최상단 import {disallowed}는 프로덕션 백업 크론의 "
        "/usr/bin/python3(+boto3, PYTHONPATH=/opt/ddona/scripts)에 없다 — 배포하면 매일 "
        "18:00 UTC 크론이 import 시점에 죽어 백업이 통째로 멈춘다(S5-d 회귀 재발)."
    )


def test_restore_db_top_level_imports_are_satisfied_by_production_cron_environment() -> None:
    path = Path(restore_db.__file__)
    imports = _top_level_import_names(path)

    disallowed = imports - _ALLOWED_TOP_LEVEL_MODULES["restore_db"]
    assert not disallowed, (
        f"ops/restore_db.py 최상단 import {disallowed}는 복원 절차가 쓰는 시스템 "
        "/usr/bin/python3(+boto3, PYTHONPATH=/opt/ddona/scripts)에 없다 — 배포하면 복원 "
        "시도가 import 시점에 죽는다(MT-9)."
    )
