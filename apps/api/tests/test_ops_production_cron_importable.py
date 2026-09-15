"""S5-e 재발 방지 + `monitoring-techspec.md` MT-9·MT-13·`monitoring-legal-draft.md` §7-6(MT-16):
프로덕션 크론이 시스템 python3로 직접 부르는 ops 모듈들이 실제로 그 환경에서 import 가능한지
고정한다.

**대상은 `backup_db.py`·`restore_db.py`·`check_resources.py`·`vacuum_bugsink.py`, 그리고 이
넷이 `ops.`로 top-level import하는 형제 모듈 `notify.py`·`db_url.py`·`pg.py`다.** VM 시스템
python3로 실제 불리는 건 앞의 넷이다 — `DEPLOY.md` §3-4가 복원 절차를 `PYTHONPATH=.
python3 -m ops.restore_db`로 명시하고, `ops/cron.d/ddona-resource-check`(MT-13)가 리소스 감시를,
`ops/cron.d/ddona-bugsink-vacuum`(MT-16)가 Bugsink 이벤트 파기를 같은 방식으로 돌린다.
**형제 모듈을 따로 검사하는 이유** — 진입점들의 허용 목록에 `ops`가 있어 `from ops.notify
import ...` 자체는 통과하지만, `notify.py` 안에서 실제로 뭘 import하는지는 아무도 안 본다.
`requests`를 몰래 넣어도 이 파일이 생기기 전엔 위 테스트들이 전부 통과했다(실측). `snapshot_redis.py`·
`compare_rows.py`는 독스트링이 `uv run`만 안내하고, `cloudrun_to_dotenv.py`는 `DEPLOY.md`가
"사문 — 실행 대상 없음"으로 선언한 죽은 코드라 이 테스트의 범위 밖이다.

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
import ops.check_resources as check_resources
import ops.db_url as db_url
import ops.notify as notify
import ops.pg as pg
import ops.restore_db as restore_db
import ops.vacuum_bugsink as vacuum_bugsink

# 모듈별 허용 목록. `ops`는 형제 모듈(`ops/pg.py`, `ops/db_url.py`, `ops/notify.py`)이라
# `PYTHONPATH=/opt/ddona/scripts`로 항상 잡힌다 — 그 형제 모듈 자신의 최상단 import는 아래
# "notify"/"db_url"/"pg" 항목이 직접 검사한다.
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
    # MT-13: 리소스 감시도 시스템 python3로 돈다(ops/cron.d/ddona-resource-check). `notify.py`와
    # 마찬가지로 stdlib만 쓴다 — `free`/`df`는 서브프로세스로 부르지 파이썬 라이브러리로 읽지
    # 않는다.
    "check_resources": {
        "argparse",
        "os",
        "subprocess",
        "sys",
        "ops",
    },
    # MT-16(monitoring-legal-draft.md §7-6): Bugsink vacuum도 시스템 python3로 돈다
    # (ops/cron.d/ddona-bugsink-vacuum). `docker exec`를 서브프로세스로 부르지 docker SDK를
    # 쓰지 않는다 — check_resources.py와 같은 이유로 stdlib만 쓴다.
    "vacuum_bugsink": {
        "argparse",
        "subprocess",
        "sys",
        "ops",
    },
    # `backup_db.py`가 `ops.notify`를 top-level import한다(alert). stdlib만 쓴다 — `http.client`는
    # `urlopen`이 던질 수 있는 예외를 잡기 위한 것으로, 네트워크 호출 자체는 여전히 `urllib.request`다.
    "notify": {
        "http",
        "json",
        "os",
        "urllib",
    },
    # `backup_db.py`·`restore_db.py`가 `ops.db_url`을 top-level import한다.
    "db_url": {
        "urllib",
    },
    # `backup_db.py`·`restore_db.py`가 `ops.pg`를 top-level import한다.
    "pg": {
        "os",
        "subprocess",
        "typing",
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


def test_check_resources_top_level_imports_are_satisfied_by_production_cron_environment() -> None:
    path = Path(check_resources.__file__)
    imports = _top_level_import_names(path)

    disallowed = imports - _ALLOWED_TOP_LEVEL_MODULES["check_resources"]
    assert not disallowed, (
        f"ops/check_resources.py 최상단 import {disallowed}는 리소스 감시 크론의 시스템 "
        "/usr/bin/python3(+boto3, PYTHONPATH=/opt/ddona/scripts)에 없다 — 배포하면 5분마다 "
        "도는 크론이 import 시점에 죽는다(MT-13)."
    )


def test_vacuum_bugsink_top_level_imports_are_satisfied_by_production_cron_environment() -> None:
    path = Path(vacuum_bugsink.__file__)
    imports = _top_level_import_names(path)

    disallowed = imports - _ALLOWED_TOP_LEVEL_MODULES["vacuum_bugsink"]
    assert not disallowed, (
        f"ops/vacuum_bugsink.py 최상단 import {disallowed}는 Bugsink vacuum 크론의 시스템 "
        "/usr/bin/python3(+boto3, PYTHONPATH=/opt/ddona/scripts)에 없다 — 배포하면 매일 도는 "
        "크론이 import 시점에 죽어 '30일 보관 후 파기' 약속이 조용히 깨진다(MT-16)."
    )


def test_notify_top_level_imports_are_satisfied_by_production_cron_environment() -> None:
    """`backup_db.py`·`check_resources.py`가 `ops.notify`를 import하므로 이 파일 자신의 최상단
    import도 직접 검사해야 한다 — 진입점 셋의 허용 목록에 있는 `ops`는 `from ops.notify import
    ...` 자체만 통과시키고 `notify.py` 내부가 뭘 import하는지는 안 본다."""
    path = Path(notify.__file__)
    imports = _top_level_import_names(path)

    disallowed = imports - _ALLOWED_TOP_LEVEL_MODULES["notify"]
    assert not disallowed, (
        f"ops/notify.py 최상단 import {disallowed}는 프로덕션 크론의 시스템 "
        "/usr/bin/python3(+boto3, PYTHONPATH=/opt/ddona/scripts)에 없다 — 배포하면 그 크론이 "
        "import 시점에 죽는다."
    )


def test_db_url_top_level_imports_are_satisfied_by_production_cron_environment() -> None:
    """`backup_db.py`·`restore_db.py`가 `ops.db_url`을 import한다 — 위 함수와 같은 이유."""
    path = Path(db_url.__file__)
    imports = _top_level_import_names(path)

    disallowed = imports - _ALLOWED_TOP_LEVEL_MODULES["db_url"]
    assert not disallowed, (
        f"ops/db_url.py 최상단 import {disallowed}는 프로덕션 크론의 시스템 "
        "/usr/bin/python3(+boto3, PYTHONPATH=/opt/ddona/scripts)에 없다 — 배포하면 그 크론이 "
        "import 시점에 죽는다."
    )


def test_pg_top_level_imports_are_satisfied_by_production_cron_environment() -> None:
    """`backup_db.py`·`restore_db.py`가 `ops.pg`를 import한다 — 위 함수와 같은 이유."""
    path = Path(pg.__file__)
    imports = _top_level_import_names(path)

    disallowed = imports - _ALLOWED_TOP_LEVEL_MODULES["pg"]
    assert not disallowed, (
        f"ops/pg.py 최상단 import {disallowed}는 프로덕션 크론의 시스템 "
        "/usr/bin/python3(+boto3, PYTHONPATH=/opt/ddona/scripts)에 없다 — 배포하면 그 크론이 "
        "import 시점에 죽는다."
    )
