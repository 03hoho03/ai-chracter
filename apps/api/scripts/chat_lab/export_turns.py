"""묶음의 방 턴 기록(`chat_turns`)을 로컬 DB 에서 읽어 묶음 폴더의 `chat-turns.jsonl` 로 쓴다 — 측정 서버의 내보내기 요청과
내보내기 명령줄이 이 함수 하나를 부른다.

읽기만 한다(받은 세션에 아무것도 남기지 않고 커밋하지 않는다). 세션을 여는 쪽은 로컬 DB 가드를 거친 주소로, 읽기 전용
트랜잭션 엔진(`read_only_engine`)을 쓴다. 쓰는 파일은 턴 기록 파일 하나뿐이고 측정 원자료(드라이버 로그·스냅숏·덤프)는 건드리지
않는다.

거부하는 것:
- 열지 않는 형식(턴 줄에 방 id 가 없는 옛 형식)과 방 id 가 uuid 가 아닌 로그.
- 런 루트의 `archive/` 아래 — git 이 추적하는 폴더라 쓰면 대화 원문이 든 파일이 공개 저장소에 커밋될 수 있다. 런 루트를 바꿔도
  저장소의 측정 기록 보관 폴더는 늘 거부한다.
- 묶음 폴더에 서로 다른 방의 드라이버 로그가 있는 것 — 턴 기록 파일 이름은 폴더에 하나라 그 폴더의 모든 로그가 그 파일을 짝으로
  읽고, 어느 방의 기록을 써야 하는지 정할 수 없다.
- 이미 있는 파일(강제가 아니면) — 손으로 고쳤거나 지금 DB 에 없는 행을 담았을 수 있어 되돌릴 수 없다. 링크는 강제여도 거부한다.
- DB 에 그 방이 없거나 행이 0 — 다른 DB 를 가리킨 것이다. 빈 파일을 남기면 묶음이 "턴 기록 있음"으로 보이고 다음 시도가 덮어쓰기
  거부에 막힌다."""

import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api.db.models import ChatTurn, StatDef
from chat_lab.bundles import CHAT_TURNS_NAME, Bundle, discover_bundles
from chat_lab.chat_turns_file import chat_turn_row, export_text, stat_def_entry
from replay.room_fixed import load_room_fixed

ARCHIVE_DIR_NAME = "archive"
# 저장소가 추적하는 측정 기록 보관 폴더(`apps/api/probe-runs/archive`).
REPO_ARCHIVE = Path(__file__).resolve().parents[2] / "probe-runs" / ARCHIVE_DIR_NAME

ExportRefusal = Literal["unsupported", "archived", "multipleRooms", "exists", "notFile", "noRoom", "noRows"]


class ExportRefusedError(Exception):
    def __init__(self, reason: ExportRefusal, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _identity(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_dev, stat.st_ino


def is_archived(path: Path, root: Path) -> bool:
    """`path` 나 그 조상 가운데 하나가 보관 폴더(런 루트의 `archive/`, 저장소의 보관 폴더)와 같은 폴더인가. 경로 글자가 아니라
    파일 시스템의 같은 폴더인지(장치·inode)로 본다 — 대소문자를 가리지 않는 파일 시스템에서 루트를 다른 대소문자로 주거나 보관
    폴더에 링크로 닿으면 글자 비교는 다른 경로로 읽어 보관 폴더에 쓴다."""
    archives = {
        identity for identity in map(_identity, (root / ARCHIVE_DIR_NAME, REPO_ARCHIVE)) if identity is not None
    }
    resolved = path.resolve()
    return any(_identity(folder) in archives for folder in (resolved, *resolved.parents))


def read_only_engine(database_url: str) -> AsyncEngine:
    """트랜잭션을 읽기 전용으로 여는 엔진. 연결을 붙잡아 두지 않는다(내보내기는 가끔 한 번이다)."""
    return create_async_engine(database_url, poolclass=NullPool, execution_options={"postgresql_readonly": True})


def _target(bundle: Bundle, *, force: bool) -> Path:
    target = bundle.log.parent / CHAT_TURNS_NAME
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ExportRefusedError("notFile", f"{target.name} 자리에 일반 파일이 아닌 것이 있다")
    if target.exists() and not force:
        raise ExportRefusedError("exists", f"{target.name} 가 이미 있다 — 바꾸려면 강제로 다시 내보낸다")
    return target


async def export_chat_turns(session: AsyncSession, bundle: Bundle, *, force: bool) -> Path:
    """쓴 파일의 경로(resolve 한 것). 거부하면 `ExportRefusedError` — 파일 시스템 검사는 DB 를 읽기 전에 한다."""
    if not bundle.supported:
        raise ExportRefusedError("unsupported", f"{bundle.path}: 턴 줄에 방 id 가 없는 옛 형식이라 열지 않는다")
    if is_archived(bundle.log.parent, bundle.root):
        raise ExportRefusedError("archived", f"{bundle.path}: {ARCHIVE_DIR_NAME}/ 아래 묶음에는 쓰지 않는다")
    rooms = sorted(
        {other.room_id for other in discover_bundles(bundle.root, folder=bundle.log.parent)} | {bundle.room_id}
    )
    if len(rooms) > 1:
        raise ExportRefusedError(
            "multipleRooms",
            f"{bundle.path}: 이 폴더의 드라이버 로그가 서로 다른 방({', '.join(rooms)})이라 내보낼 방을 정할 수 없다",
        )
    try:
        room_id = uuid.UUID(bundle.room_id)
    except ValueError as error:
        raise ExportRefusedError("unsupported", f"{bundle.path}: 방 id 가 uuid 가 아니다") from error
    _target(bundle, force=force)

    fixed = await load_room_fixed(session, room_id, allow_character=True)
    if fixed is None:
        raise ExportRefusedError("noRoom", f"DB 에 방 {room_id} 이 없다 — 이 런을 돈 DB 인지 확인한다")
    turns = (
        await session.scalars(
            select(ChatTurn)
            .where(ChatTurn.chat_room_id == room_id)
            .order_by(ChatTurn.turn_number, ChatTurn.created_at, ChatTurn.id)
        )
    ).all()
    if not turns:
        raise ExportRefusedError("noRows", f"DB 에 방 {room_id} 의 턴 기록이 하나도 없다")
    stats: list[StatDef] = []
    if fixed.pinned_starting_setup_id is not None:
        stats = list(
            (
                await session.scalars(
                    select(StatDef)
                    .where(StatDef.starting_setup_id == fixed.pinned_starting_setup_id)
                    .order_by(StatDef.order)
                )
            ).all()
        )
    text = export_text(
        room_id=bundle.room_id,
        exported_at=datetime.now(UTC),
        stat_defs=[stat_def_entry(stat) for stat in stats],
        rows=[chat_turn_row(turn) for turn in turns],
    )

    # DB 를 기다리는 동안 다른 요청이 같은 자리에 썼을 수 있어 바꾸기 직전에 다시 본다(이 사이에는 기다림이 없다).
    target = _target(bundle, force=force)
    _write_whole(target, text)
    return target.resolve()


def _write_whole(target: Path, text: str) -> None:
    """같은 폴더의 임시 파일에 다 쓴 뒤 이름을 바꾼다 — 쓰다 끊겨도 반쯤 쓴 턴 기록 파일이 남지 않는다."""
    fd, temporary = tempfile.mkstemp(prefix=f".{CHAT_TURNS_NAME}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
