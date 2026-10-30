"""턴 기록(`chat_turns`) 내보내기 — 함수, 측정 서버의 내보내기 요청, 명령줄.

`chat_turns` 는 런 당시 로컬 DB 에만 있고 그 볼륨은 대개 지워져 묶음 옆 파일로 옮겨 둔다. 런은 측정 드라이버를 테스트 앱에
실제로 붙여 만들고(`driver_harness.drive_room`), 내보내기는 그 테스트 트랜잭션의 세션(`db_session`)을 받아 행을 읽는다 — 앱이
남긴 행은 그 트랜잭션 안에만 있다. 서버의 기본 경로(설정한 DB 주소로 엔진을 만드는 것)는 다른 연결이라 그 행을 보지 못한다.
그 성질로 "다른 DB 를 가리키면 빈 파일을 남기지 않는다"를 본다."""

import hashlib
import os
import shutil
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import chat_lab_export_turns
from api.core.config import settings
from api.db.models import ChatTurn
from api.llm.pricing import PRICES_AS_OF
from chat_lab.app import create_app
from chat_lab.bundles import CHAT_TURNS_NAME, DUMP_NAME, SNAPSHOTS_NAME, Bundle, discover_bundles
from chat_lab.chat_turns_file import chat_turn_row, export_text, parse_chat_turns, prices_sha256
from chat_lab import export_turns
from chat_lab.export_turns import ExportRefusedError, export_chat_turns
from driver_harness import (
    _DRIVE_RAISE_RULE,
    DRIVE_HIDDEN_RULE,
    DRIVE_HIDDEN_STAT_NAME,
    DRIVE_STAT_NAME,
    DrivenRoom,
    drive_room,
    says,
)

UNREACHABLE_DB = "postgresql+asyncpg://lab:lab@127.0.0.1:1/chat_lab_unreachable"
RAW_FILES = ("chat.jsonl", SNAPSHOTS_NAME, DUMP_NAME)


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8791")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raw_shas(folder: Path) -> dict[str, str]:
    return {name: _sha(folder / name) for name in RAW_FILES}


@asynccontextmanager
async def _borrowed(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """테스트 세션을 닫지 않고 빌려준다 — 서버·명령줄이 쓰는 세션 자리에 넣는다."""
    yield session


async def _hidden_root(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, folder: str = "runs/a"
) -> tuple[Path, DrivenRoom, Path]:
    """턴 2 에 숨김 스탯이, 턴 3 에 보이는 스탯이 바뀌는 세 턴 런을 `tmp_path / "root" / folder` 에 둔다."""
    root = tmp_path / "root"
    target = root / folder
    driven = await drive_room(
        db_session,
        monkeypatch,
        tmp_path,
        script=says(3),
        failing_generations=(),
        stat_verdicts={2: (DRIVE_HIDDEN_RULE,), 3: (_DRIVE_RAISE_RULE,)},
        hidden_stat=True,
        export_dir=target,
    )
    assert driven.hidden_stat_id is not None
    return root, driven, target


def _bundle(root: Path) -> Bundle:
    [bundle] = discover_bundles(root)
    return bundle


async def _db_rows(db_session: AsyncSession, room_id: uuid.UUID) -> list[dict[str, Any]]:
    turns = await db_session.scalars(
        sa.select(ChatTurn).where(ChatTurn.chat_room_id == room_id).order_by(ChatTurn.turn_number)
    )
    return [chat_turn_row(turn) for turn in turns.all()]


async def test_the_export_writes_every_row_with_the_price_table_and_stat_definitions_beside_the_untouched_raw_files(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """내보낸 파일은 그 방의 턴 기록 행 전부, 단가표 기준일과 표 내용의 해시(기준일만으로는 판을 가르지 못한다), 시작 설정의
    스탯 정의(숨김 스탯을 이름과 숨김 표시로 보이려면 있어야 한다)를 싣는다. 측정 원자료(드라이버 로그·스냅숏·덤프)는 한
    바이트도 바뀌지 않고, 폴더에는 턴 기록 파일 하나만 더해진다(임시 파일이 남지 않는다)."""
    root, driven, folder = await _hidden_root(db_session, monkeypatch, tmp_path)
    before = _raw_shas(folder)
    listing = sorted(os.listdir(folder))

    written = await export_chat_turns(db_session, _bundle(root), force=False)

    assert written == (folder / CHAT_TURNS_NAME).resolve()
    assert _raw_shas(folder) == before
    assert sorted(os.listdir(folder)) == sorted([*listing, CHAT_TURNS_NAME])
    export = parse_chat_turns(written.read_text(encoding="utf-8"))
    assert export.room_id == str(driven.room_id)
    assert (export.prices_as_of, export.prices_sha256) == (PRICES_AS_OF.isoformat(), prices_sha256())
    assert [(d.id, d.name, d.hidden_from_player) for d in export.stat_defs] == [
        (str(driven.trust_id), DRIVE_STAT_NAME, False),
        (str(driven.hidden_stat_id), DRIVE_HIDDEN_STAT_NAME, True),
    ]
    rows = await _db_rows(db_session, driven.room_id)
    assert len(rows) == 3
    reference = parse_chat_turns(
        export_text(room_id=str(driven.room_id), exported_at=datetime.now(UTC), stat_defs=[], rows=rows)
    )
    assert export.rows == reference.rows
    assert export.problems == []


async def test_an_existing_export_is_kept_unless_forced(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """이미 있는 턴 기록 파일은 손으로 고쳤거나 지금 DB 에 없는 행을 담았을 수 있어, 묻지 않고 덮으면 되돌릴 수 없다. 강제 없이는
    거부하고 파일은 그대로, 강제면 새로 내보낸 것으로 바뀐다. 그 자리가 링크면 강제여도 거부한다 — 묶음은 링크 짝을 읽지 않으므로
    사람이 일부러 둔 것이고, 바꾸면 그 링크가 말없이 사라진다."""
    root, driven, folder = await _hidden_root(db_session, monkeypatch, tmp_path)
    target = folder / CHAT_TURNS_NAME
    target.write_text("손으로 둔 파일\n", encoding="utf-8")

    with pytest.raises(ExportRefusedError) as refused:
        await export_chat_turns(db_session, _bundle(root), force=False)
    assert refused.value.reason == "exists"
    assert target.read_text(encoding="utf-8") == "손으로 둔 파일\n"

    await export_chat_turns(db_session, _bundle(root), force=True)
    assert parse_chat_turns(target.read_text(encoding="utf-8")).room_id == str(driven.room_id)

    elsewhere = tmp_path / "elsewhere.jsonl"
    target.replace(elsewhere)
    target.symlink_to(elsewhere)
    with pytest.raises(ExportRefusedError) as linked:
        await export_chat_turns(db_session, _bundle(root), force=True)
    assert linked.value.reason == "notFile"
    assert target.is_symlink()


async def test_a_room_missing_from_the_database_or_without_rows_leaves_no_file(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """다른 DB 를 가리키면 방이 없거나 행이 0 이다. 그때 빈 파일을 쓰면 묶음이 "턴 기록 있음"으로 보이고, 다음 시도가 덮어쓰기
    거부에 막힌다. 그래서 둘 다 파일을 쓰지 않고 실패해야 한다."""
    root, driven, folder = await _hidden_root(db_session, monkeypatch, tmp_path)
    stranger = root / "runs" / "stranger"
    stranger.mkdir(parents=True)
    for name in RAW_FILES:
        text = (folder / name).read_text(encoding="utf-8")
        (stranger / name).write_text(text.replace(str(driven.room_id), str(uuid.uuid4())), encoding="utf-8")
    bundles = {bundle.log.parent.name: bundle for bundle in discover_bundles(root)}

    with pytest.raises(ExportRefusedError) as no_room:
        await export_chat_turns(db_session, bundles["stranger"], force=False)
    await db_session.execute(sa.delete(ChatTurn).where(ChatTurn.chat_room_id == driven.room_id))
    with pytest.raises(ExportRefusedError) as no_rows:
        await export_chat_turns(db_session, bundles["a"], force=False)

    assert (no_room.value.reason, no_rows.value.reason) == ("noRoom", "noRows")
    assert not (stranger / CHAT_TURNS_NAME).exists()
    assert not (folder / CHAT_TURNS_NAME).exists()


async def test_bundles_under_the_archive_folder_are_never_written(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """런 루트의 `archive/` 는 git 이 추적하는 폴더라, 거기 쓰면 대화 원문이 든 파일이 공개 저장소에 커밋될 수 있다. 함수도
    서버 요청도(403) 그 아래에는 쓰지 않는다 — 강제를 줘도."""
    root, _, folder = await _hidden_root(db_session, monkeypatch, tmp_path, folder="archive/2026-10/a")
    bundle = _bundle(root)

    with pytest.raises(ExportRefusedError) as refused:
        await export_chat_turns(db_session, bundle, force=True)
    app = create_app(root=root, database_url=None, session_factory=lambda: _borrowed(db_session))
    async with _client(app) as client:
        answer = await client.post(f"/runs/{bundle.run_id}/export-turns", json={"force": True})

    assert refused.value.reason == "archived"
    assert (answer.status_code, answer.json()["reason"]) == (403, "archived")
    assert not (folder / CHAT_TURNS_NAME).exists()


async def test_an_archive_folder_reached_by_another_spelling_is_still_refused(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """보관 폴더 판정은 경로 글자가 아니라 같은 폴더인지(장치·inode)로 한다. 글자로 견주면 두 경우에 보관 폴더에 쓴다.
    - 런 루트의 `archive` 가 다른 폴더로 가는 링크일 때 — 묶음은 링크 너머의 실제 폴더 경로로 잡혀 `archive` 글자가 없다. 이
      경우는 어느 플랫폼에서나 같다.
    - 저장소의 보관 폴더에 대소문자가 다른 루트로 닿을 때 — 대소문자를 가리지 않는 파일 시스템(macOS 기본)에서는 같은 폴더인데
      글자가 다르다. 대소문자를 가리는 파일 시스템에서는 그 철자가 없어 링크로 만들어 둔다(그때는 resolve 가 실제 철자로 풀어
      글자 비교도 통과하지만, 판정이 맞는지는 그대로 본다)."""
    _, _, source = await _hidden_root(db_session, monkeypatch, tmp_path)

    linked_root = tmp_path / "linked"
    shutil.copytree(source, linked_root / "vault" / "a")
    (linked_root / "archive").symlink_to(linked_root / "vault", target_is_directory=True)
    with pytest.raises(ExportRefusedError) as through_link:
        await export_chat_turns(db_session, _bundle(linked_root), force=True)

    real = tmp_path / "Lab"
    shutil.copytree(source, real / "probe" / "archive" / "a")
    monkeypatch.setattr(export_turns, "REPO_ARCHIVE", (real / "probe" / "archive").resolve())
    respelled = tmp_path / "lAB"
    if not respelled.exists():
        respelled.symlink_to(real, target_is_directory=True)
    with pytest.raises(ExportRefusedError) as other_case:
        await export_chat_turns(db_session, _bundle(respelled), force=True)

    assert (through_link.value.reason, other_case.value.reason) == ("archived", "archived")
    assert not (linked_root / "vault" / "a" / CHAT_TURNS_NAME).exists()
    assert not (real / "probe" / "archive" / "a" / CHAT_TURNS_NAME).exists()


async def test_a_folder_holding_driver_logs_of_different_rooms_is_refused_everywhere(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """턴 기록 파일 이름은 폴더에 하나라 그 폴더의 드라이버 로그가 모두 그 파일을 짝으로 읽는다. 방이 다른 로그가 같은 폴더에
    있으면 어느 방의 기록을 써도 다른 로그에는 틀린 짝이 되므로, 내보내기 함수가 거부하고 측정 서버(422)와 명령줄(1)이 같은
    규칙을 쓴다. 같은 방 로그만 여럿이면 거부하지 않는다."""
    root, driven, folder = await _hidden_root(db_session, monkeypatch, tmp_path)
    log = (folder / "chat.jsonl").read_text(encoding="utf-8")
    (folder / "retry.jsonl").write_text(log, encoding="utf-8")
    (folder / "stranger.jsonl").write_text(log.replace(str(driven.room_id), str(uuid.uuid4())), encoding="utf-8")
    bundles = {bundle.log.name: bundle for bundle in discover_bundles(root)}
    app = create_app(root=root, database_url=None, session_factory=lambda: _borrowed(db_session))
    monkeypatch.setattr(chat_lab_export_turns, "open_session", lambda url: _borrowed(db_session))

    with pytest.raises(ExportRefusedError) as refused:
        await export_chat_turns(db_session, bundles["chat.jsonl"], force=False)
    async with _client(app) as client:
        answer = await client.post(f"/runs/{bundles['chat.jsonl'].run_id}/export-turns", json={"force": False})
    command = await chat_lab_export_turns.run(
        ["--run-dir", str(folder), "--database-url", UNREACHABLE_DB, "--root", str(root)]
    )
    assert not (folder / CHAT_TURNS_NAME).exists()
    (folder / "stranger.jsonl").unlink()
    written = await export_chat_turns(db_session, bundles["chat.jsonl"], force=False)

    assert refused.value.reason == "multipleRooms"
    assert (answer.status_code, answer.json()["reason"]) == (422, "multipleRooms")
    assert command == 1
    assert parse_chat_turns(written.read_text(encoding="utf-8")).room_id == str(driven.room_id)


async def test_a_server_export_feeds_cost_and_hidden_stats_into_the_next_detail(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """내보내기 요청은 같은 함수를 부르고, 쓴 파일은 다시 훑지 않아도 그 묶음의 짝이 된다. 그래서 다음 상세에 원가와 숨김
    스탯(이름·숨김 표시)이 나와야 한다 — 내보내기 전에는 원가가 "내보내기 필요"(없음)이고 숨김 스탯 계열이 없다. 두 번째
    요청은 강제 없이 409, 강제면 다시 쓴다. 그 자리가 링크면 강제로도 못 쓰므로 409 가 아니라 422 다 — 409 는 웹이 "강제로 다시
    내보내기"를 권하는 신호라, 여기서 409 를 내면 권하고 실패하기를 되풀이한다."""
    root, driven, folder = await _hidden_root(db_session, monkeypatch, tmp_path)
    bundle = _bundle(root)
    app = create_app(root=root, database_url=None, session_factory=lambda: _borrowed(db_session))
    hidden = str(driven.hidden_stat_id)

    async with _client(app) as client:
        before = (await client.get(f"/runs/{bundle.run_id}")).json()
        exported = await client.post(f"/runs/{bundle.run_id}/export-turns", json={"force": False})
        after = (await client.get(f"/runs/{bundle.run_id}")).json()
        listed = (await client.get("/runs")).json()["items"]
        again = await client.post(f"/runs/{bundle.run_id}/export-turns", json={"force": False})
        forced = await client.post(f"/runs/{bundle.run_id}/export-turns", json={"force": True})
        target = folder / CHAT_TURNS_NAME
        target.replace(tmp_path / "elsewhere.jsonl")
        target.symlink_to(tmp_path / "elsewhere.jsonl")
        linked = await client.post(f"/runs/{bundle.run_id}/export-turns", json={"force": True})

    assert before["cost"] is None
    assert hidden not in {series["id"] for series in before["series"]}
    assert exported.status_code == 200
    body = exported.json()
    assert body["path"] == f"runs/a/{CHAT_TURNS_NAME}"
    assert (body["run"]["hasChatTurns"], body["run"]["costUsd"] is not None) == (True, True)
    assert after["cost"] is not None
    assert after["run"]["costUsd"] == body["run"]["costUsd"]
    [series] = [series for series in after["series"] if series["id"] == hidden]
    assert (series["name"], series["hidden"], series["source"]) == (DRIVE_HIDDEN_STAT_NAME, True, "chatTurns")
    assert [(point["turn"], point["value"]) for point in series["points"]] == [(2, 70.0)]
    assert after["mismatches"] == []
    [item] = listed
    assert item["hasChatTurns"] is True
    assert (again.status_code, again.json()["reason"], forced.status_code) == (409, "exists", 200)
    assert (linked.status_code, linked.json()["reason"]) == (422, "notFile")
    assert (folder / CHAT_TURNS_NAME).is_symlink()


async def test_the_server_opens_its_database_only_when_exporting(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """세션을 따로 주지 않은 서버는 설정한 DB 주소로 엔진을 만든다. 엔진은 첫 내보내기 요청 때 하나만 만들고, 목록·상세는
    만들지 않는다. 그 엔진은 다른 연결이라 이 테스트 트랜잭션의 방을 보지 못하므로, 내보내기는 "방 없음"(422)으로 파일 없이
    끝난다 — 다른 DB 를 가리킨 서버가 빈 파일을 남기지 않는다는 것과 같은 일이다. 그 엔진의 트랜잭션은 읽기 전용이다(내보내기는
    읽기만 한다 — 실수로 쓰는 코드가 들어와도 DB 가 거부한다)."""
    root, _, folder = await _hidden_root(db_session, monkeypatch, tmp_path)
    bundle = _bundle(root)
    engines: list[AsyncEngine] = []
    original = AsyncEngine.__init__

    def counting(self: AsyncEngine, *args: Any, **kwargs: Any) -> None:
        engines.append(self)
        original(self, *args, **kwargs)

    monkeypatch.setattr(AsyncEngine, "__init__", counting)
    app = create_app(root=root, database_url=os.environ["DATABASE_URL"])

    async with _client(app) as client:
        await client.get("/runs")
        await client.get(f"/runs/{bundle.run_id}")
        assert engines == []
        first = await client.post(f"/runs/{bundle.run_id}/export-turns", json={"force": False})
        second = await client.post(f"/runs/{bundle.run_id}/export-turns", json={"force": False})

    assert [(answer.status_code, answer.json()["reason"]) for answer in (first, second)] == [(422, "noRoom")] * 2
    assert len(engines) == 1
    assert not (folder / CHAT_TURNS_NAME).exists()
    async with engines[0].connect() as connection:
        assert await connection.scalar(sa.text("SHOW transaction_read_only")) == "on"
    for engine in engines:
        await engine.dispose()


async def test_the_export_command_exit_codes(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """명령줄은 0 성공, 1 입력 없음·거부, 3 로컬이 아닌 DB(2 는 argparse 의 인자 오류라 겹치지 않는다). DB 주소를 주지
    않으면 설정의 주소를 쓰고 그 주소에도 같은 가드를 건다. DB 가드는 입력을 보기 전에 먼저 걸린다. 성공 경로는 명령줄이 여는
    세션 자리에 테스트 세션을 넣어 본다. 명령줄 진입은 `asyncio.run` 이라 이 테스트 루프 안에서는 그 안의 비동기 본체를 부른다."""
    root, driven, folder = await _hidden_root(db_session, monkeypatch, tmp_path)
    shutil.copytree(folder, root / "archive" / "a")
    remote = "postgresql+asyncpg://u:p@postgres:5432/ai_character_chat"
    local = UNREACHABLE_DB

    async def run(*argv: str) -> int:
        return await chat_lab_export_turns.run([*argv, "--root", str(root)])

    monkeypatch.setattr(chat_lab_export_turns, "open_session", lambda url: _borrowed(db_session))

    assert await run("--run-dir", str(folder), "--database-url", remote) == 3
    assert await run("--run-dir", str(tmp_path / "nowhere"), "--database-url", remote) == 3
    monkeypatch.setattr(settings, "database_url", remote)
    assert await run("--run-dir", str(folder)) == 3
    assert await run("--run-dir", str(tmp_path / "nowhere"), "--database-url", local) == 1
    assert await run("--run-dir", str(tmp_path), "--database-url", local) == 1
    assert await run("--run-dir", str(root / "runs"), "--database-url", local) == 1
    assert await run("--run-dir", str(root / "archive" / "a"), "--database-url", local) == 1
    assert not (folder / CHAT_TURNS_NAME).exists()

    assert await run("--run-dir", str(folder), "--database-url", local) == 0
    assert parse_chat_turns((folder / CHAT_TURNS_NAME).read_text(encoding="utf-8")).room_id == str(driven.room_id)
    assert await run("--run-dir", str(folder), "--database-url", local) == 1
    assert await run("--run-dir", str(folder), "--database-url", local, "--force") == 0
    assert not (root / "archive" / "a" / CHAT_TURNS_NAME).exists()
