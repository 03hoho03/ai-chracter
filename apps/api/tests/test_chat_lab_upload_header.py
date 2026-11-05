"""측정 서버의 묶음 계약 판과 올리기 머리(만든 커밋·출처 칸).

호스팅 서비스는 올라온 묶음의 JSON 바이트 sha256 을 판 키로 쓴다. 그래서 묶음 응답에는 계약 판(`contractVersion`)만 싣고, 만든
커밋(`sourceCommit`)과 출처 칸(`provenance`)은 올리기용 요청에만 따로 낸다 — 둘이 묶음 안에 있으면 측정 서버 커밋만 바뀌었거나
출처를 다시 물었을 뿐 내용이 같은 묶음이 새 판이 된다. 출처 칸은 그 런이 로컬 측정 서버에서 테스트 계정(`@example.com`)으로만
돈 것인지를 불·수로만 말한다 — 서비스로 가는 응답에 이메일을 싣지 않는다.

런은 측정 드라이버를 테스트 앱에 실제로 붙여 만든다(`driver_harness.drive_room`). 드라이버는 테스트 클라이언트 주소
(`http://testserver`)로 돌고 그 주소를 meta 줄의 `base` 에 적는다. 로컬 측정 서버로 돈 런은 묶음 폴더 드라이버 로그의 그 칸만
바꿔 흉내 내고, 프로브 묶음(meta 줄이 없다)은 그 줄을 지워 흉내 낸다. 출처 조회는 테스트 트랜잭션의 세션을 받아
(`session_factory`) 드라이버가 만든 방·사용자를 보고, 사용자·작가 상태는 그 세션으로 바꾼다. 만든 커밋은 git 을 부르는 자리
(`chat_lab.source_commit.run_git` — git 인자를 받아 표준 출력을 돌려준다)를 바꿔 깨끗한 트리와 더러운 트리를 흉내 낸다. 측정 서버는
만든 커밋을 띄울 때 한 번 읽으므로(`chat_lab.source_commit.read_source_commit`), 테스트 앱도 만들 때 읽어 넘긴다(`_app`) — 띄우는
경로 자체는 진입점(`chat_lab_server.main`)으로 본다(`_start`)."""

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest
import sqlalchemy as sa
import uvicorn
from fastapi import FastAPI
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import ChatRoom, Content, User
import chat_lab_server
from api.db.session import engine
from chat_lab.app import create_app
from chat_lab.bundles import CHAT_TURNS_NAME, DUMP_NAME, SNAPSHOTS_NAME
from chat_lab.run_id import encode_run_id
from chat_lab.schemas import SourceCommit
from driver_harness import DrivenRoom, drive_room, says
from factories import _collect_engines, _count_llm_and_redis, _make_user

# 로컬 주소라 가드는 통과하지만 아무것도 듣지 않는 포트 — 접속하려 들면 곧바로 실패한다.
UNREACHABLE_DB = "postgresql+asyncpg://lab:lab@127.0.0.1:1/chat_lab_unreachable"
BASE_URL = "http://127.0.0.1:8791"
DRIVER_LOG = "chat.jsonl"
RUN_FILES = (DRIVER_LOG, SNAPSHOTS_NAME, DUMP_NAME)
# 드라이버 장치가 테스트 클라이언트로 돌며 meta 줄에 적는 주소.
HARNESS_BASE = "http://testserver"
# 측정 서버의 로컬 DB 가드와 같은 호스트 셋 — 이 주소로 돈 런만 로컬 측정 서버의 런이다.
LOOPBACK_BASES = ("http://127.0.0.1:8793", "http://localhost:8793", "http://[::1]:8793")
# 루프백이 아닌 주소 — 테스트 클라이언트 주소(테스트가 만든 합성 묶음), 같은 망의 다른 기기, 앞머리만 루프백 주소인 이름.
FOREIGN_BASES = (HARNESS_BASE, "http://192.168.0.10:8793", "http://127.0.0.1.evil.example:8793")
# 측정 서버가 로컬로 받지 않는 DB 주소 — 운영 compose 서비스명, 바깥 주소, 주소 칸은 로컬이지만 쿼리로 다른 곳에 붙는 것.
NON_LOCAL_DATABASES = (
    "postgresql+asyncpg://u:p@postgres:5432/ai_character_chat",
    "postgresql+asyncpg://u:p@db.example.com/x",
    "postgresql+asyncpg://u:p@localhost/x?host=postgres",
)
CLEAN_COMMIT = "0123456789abcdef0123456789abcdef01234567"
OTHER_COMMIT = "fedcba9876543210fedcba9876543210fedcba98"
DIRTY_STATUS = " M apps/api/scripts/chat_lab/app.py\n"
EMAIL_SHAPE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# 테스트 계정이 아닌 사용자의 도메인. 끝이 `example.com` 이라 `@` 없이 견주면 테스트 계정으로 읽힌다.
OUTSIDE_DOMAIN = "notexample.com"
# 모든 판정을 통과한 출처 칸.
PASSING: dict[str, bool | int | None] = {
    "passed": True,
    "baseLocal": True,
    "roomFound": True,
    "ownerInExampleDomain": True,
    "outsideUsers": 0,
    "exemptedUsers": 0,
    "authorInExampleDomain": True,
}
# 지금 모델에는 있지만 올려 둘 대표 런의 복원 DB 에는 없을 수 있는 칸.
NEWER_COLUMNS = {
    "chat_rooms": ("chat_model", "memory_forget_generation"),
    "contents": ("novel_buyers_kept", "novel_permission", "derived_novels_visible", "edited_at"),
    "users": ("identity_ci_hmac", "identity_verified_at"),
}
# 출처 판정이 읽는 칸 — 방의 주인·작품, 작품의 작가, 사용자의 이메일·탈퇴 칸과 그것들을 잇는 id.
READ_COLUMNS = {
    "chat_rooms": {"id", "user_id", "content_id"},
    "contents": {"id", "creator_user_id"},
    "users": {"id", "email", "deleted_at"},
}


class FakeGit:
    """`chat_lab.source_commit.run_git` 자리에 넣는 git. 받은 인자를 적어 두고, `rev-parse` 에는 커밋 id 를, `status` 에는 추적하는
    파일의 바뀐 목록(비면 깨끗한 트리)을 낸다. 추적하지 않는 파일 목록(`untracked`)은 실제 git 처럼 `--untracked-files=no` 를 받지
    않았을 때만 덧붙인다. `failures` 에 든 명령(`rev-parse`·`status`)은 그 예외로 실패한다 — 진짜 `run_git` 은 git 이 없으면
    `OSError`, 0 이 아닌 종료(checkout 이 아님 등)면 `subprocess.CalledProcessError` 를 낸다. 그 밖의 git 호출은 실패다."""

    def __init__(self) -> None:
        self.commit = CLEAN_COMMIT
        self.status = ""
        self.untracked = ""
        self.failures: dict[str, Exception] = {}
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> str:
        self.calls.append(list(args))
        for command, error in self.failures.items():
            if command in args:
                raise error
        if "rev-parse" in args:
            return f"{self.commit}\n"
        if "status" in args:
            return self.status + ("" if "--untracked-files=no" in args else self.untracked)
        raise AssertionError(f"예상하지 않은 git 호출: {list(args)}")


def _use_git(monkeypatch: pytest.MonkeyPatch) -> FakeGit:
    git = FakeGit()
    monkeypatch.setattr("chat_lab.source_commit.run_git", git)
    return git


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL)


@asynccontextmanager
async def _borrowed(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """테스트 세션을 닫지 않고 빌려준다 — 서버가 쓰는 세션 자리에 넣는다."""
    yield session


def _startup_commit() -> SourceCommit | None:
    """서버를 띄울 때처럼 만든 커밋을 읽는다 — git 이 실패했으면 None."""
    from chat_lab.source_commit import read_source_commit

    return read_source_commit()


def _app(root: Path, db_session: AsyncSession) -> FastAPI:
    """만든 커밋을 만들 때 한 번 읽어 넘기고, 출처 조회·내보내기가 테스트 세션을 쓰는 앱."""
    return create_app(
        root=root,
        database_url=None,
        session_factory=lambda: _borrowed(db_session),
        source_commit=_startup_commit(),
    )


def _start(monkeypatch: pytest.MonkeyPatch, root: Path, database_url: str) -> FastAPI:
    """진입점(`chat_lab_server.main`)으로 서버를 띄운다 — 서버 돌리기(`uvicorn.run`)만 가로채 넘겨받은 앱을 돌려준다."""
    started: list[FastAPI] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: started.append(app))
    assert chat_lab_server.main(["--root", str(root), "--database-url", database_url]) == 0
    [app] = started
    return app


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _keys(value: Any) -> set[str]:
    """JSON 값 안의 모든 객체 키(깊이 상관없이)."""
    keys: set[str] = set()
    if isinstance(value, dict):
        keys |= set(value)
        for item in value.values():
            keys |= _keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _keys(item)
    return keys


def _records(log: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_records(log: Path, records: list[dict[str, Any]]) -> None:
    log.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")


def _meta(folder: Path) -> dict[str, Any]:
    [meta] = [record for record in _records(folder / DRIVER_LOG) if record.get("kind") == "meta"]
    return meta


def _set_base(folder: Path, base: str | None) -> None:
    """묶음 폴더 드라이버 로그의 meta 줄 `base` 를 바꾼다. None 이면 meta 줄을 지운다(프로브 묶음에는 그 줄이 없다)."""
    log = folder / DRIVER_LOG
    records = _records(log)
    [meta] = [record for record in records if record.get("kind") == "meta"]
    if base is None:
        records.remove(meta)
    else:
        meta["base"] = base
    _write_records(log, records)


def _run_id(root: Path, folder: Path) -> str:
    return encode_run_id(root, folder / DRIVER_LOG)


def _variant(
    root: Path, folder: Path, name: str, *, base: str | None, rooms: tuple[uuid.UUID, uuid.UUID] | None = None
) -> str:
    """묶음 폴더를 같은 부모 아래 `name` 으로 복사하고 meta 주소를 `base` 로 바꾼다(`_set_base`). `rooms` 를 주면 세 파일의 방
    id 를 앞의 것에서 뒤의 것으로 바꾼다. 새 묶음의 id 를 돌려준다."""
    target = folder.parent / name
    shutil.copytree(folder, target)
    if rooms is not None:
        old, new = (str(room) for room in rooms)
        for file_name in RUN_FILES:
            path = target / file_name
            path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    _set_base(target, base)
    return _run_id(root, target)


def _variant_meta(root: Path, folder: Path, name: str, edit: Callable[[dict[str, Any]], object]) -> str:
    """묶음 폴더를 같은 부모 아래 `name` 으로 복사하고 그 드라이버 로그의 meta 줄을 `edit` 로 고친다. 새 묶음의 id 를 돌려준다."""
    target = folder.parent / name
    shutil.copytree(folder, target)
    log = target / DRIVER_LOG
    records = _records(log)
    [meta] = [record for record in records if record.get("kind") == "meta"]
    edit(meta)
    _write_records(log, records)
    return _run_id(root, target)


async def _drive(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, DrivenRoom, Path]:
    """두 턴 런 하나를 `tmp_path / "root" / "runs" / "a"` 에 둔다 — meta 주소는 드라이버 장치가 적은 그대로다. (런 루트, 돈 방,
    묶음 폴더)."""
    root = tmp_path / "root"
    folder = root / "runs" / "a"
    driven = await drive_room(
        db_session, monkeypatch, tmp_path, script=says(2), failing_generations=(), stat_verdicts={}, export_dir=folder
    )
    return root, driven, folder


async def _local_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, DrivenRoom, Path]:
    """`_drive` 의 런을 로컬 측정 서버(루프백 주소)로 돈 런으로 바꿔 둔다."""
    root, driven, folder = await _drive(db_session, monkeypatch, tmp_path)
    _set_base(folder, LOOPBACK_BASES[0])
    return root, driven, folder


async def _header(client: httpx.AsyncClient, run_id: str, exempt: Sequence[str] = ()) -> dict[str, Any]:
    """올리기 머리를 받아 모양을 본다 — 칸은 만든 커밋과 출처 칸 둘뿐이고, 출처 칸은 정해진 칸의 불·수만이며, 응답 어디에도
    이메일 꼴 글자나 보낸 예외 이메일이 없다."""
    answer = await client.post(f"/runs/{run_id}/upload-header", json={"exemptEmails": list(exempt)})
    assert answer.status_code == 200, answer.text
    assert EMAIL_SHAPE.search(answer.text) is None
    assert all(email not in answer.text for email in exempt)
    body: dict[str, Any] = answer.json()
    assert set(body) == {"sourceCommit", "provenance"}
    provenance = body["provenance"]
    assert set(provenance) == set(PASSING)
    assert all(value is None or isinstance(value, bool | int) for value in provenance.values())
    return body


async def _provenance(client: httpx.AsyncClient, run_id: str, exempt: Sequence[str] = ()) -> dict[str, Any]:
    provenance: dict[str, Any] = (await _header(client, run_id, exempt))["provenance"]
    return provenance


async def _room(db_session: AsyncSession, room_id: uuid.UUID) -> ChatRoom:
    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    return room


async def _outside_user(db_session: AsyncSession, label: str) -> User:
    """탈퇴하지 않은, 테스트 계정 밖 도메인의 사용자."""
    user = _make_user(email=f"{label}-{uuid.uuid4()}@{OUTSIDE_DOMAIN}")
    db_session.add(user)
    await db_session.flush()
    return user


async def _set_author(db_session: AsyncSession, room: ChatRoom, author: User) -> None:
    content = await db_session.get(Content, room.content_id)
    assert content is not None
    content.creator_user_id = author.id
    await db_session.flush()


async def _move_owner_outside(db_session: AsyncSession, room: ChatRoom) -> str:
    """방 주인의 이메일을 테스트 계정 밖으로 바꾸고 그 이메일을 돌려준다."""
    owner = await db_session.get(User, room.user_id)
    assert owner is not None
    owner.email = f"owner-{uuid.uuid4()}@{OUTSIDE_DOMAIN}"
    await db_session.flush()
    return owner.email


@contextmanager
def _statements() -> Iterator[list[str]]:
    """그동안 실행된 SQL 문 글자를 모은다(값은 바인드 인자라 글자에 없다)."""
    seen: list[str] = []

    def record(_connection: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        seen.append(statement)

    sa.event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", record)


async def test_every_bundle_answer_carries_contract_version_one_and_nothing_from_the_upload_header(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """원문 포함·제외 두 묶음 응답 모두 계약 판 1 을 싣고, 꼭대기 칸은 계약 판·원문 여부·상세·지표·턴뿐이다 — 만든 커밋과 출처 칸은
    어느 깊이에도 없다. 같은 런의 묶음은 다시 받아도, 그사이 올리기 머리를 물어도, 트리가 더러워진 뒤 서버를 새로 띄워도 바이트가
    같다(sha256) — 판 키가 묶음 바이트로만 정해진다는 전제다. 요청은 git 을 부르지 않는다(만든 커밋은 띄울 때 읽는다)."""
    root, _, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    git = _use_git(monkeypatch)

    async def bundles(client: httpx.AsyncClient) -> list[httpx.Response]:
        return [await client.get(f"/runs/{run_id}/bundle", params={"raw": raw}) for raw in ("true", "false")]

    first_app = _app(root, db_session)
    reads = len(git.calls)
    async with _client(first_app) as client:
        first = await bundles(client)
        await _header(client, run_id)
        again = await bundles(client)
    assert len(git.calls) == reads
    git.commit, git.status = OTHER_COMMIT, DIRTY_STATUS
    async with _client(_app(root, db_session)) as client:
        restarted_header = await _header(client, run_id)
        restarted = await bundles(client)

    assert restarted_header["sourceCommit"] == {"commit": OTHER_COMMIT, "dirty": True}
    assert [answer.status_code for answer in first + again + restarted] == [200] * 6
    for answer in first:
        body = answer.json()
        assert body["contractVersion"] == 1
        assert set(body) == {"contractVersion", "raw", "detail", "metrics", "turns"}
        assert {"sourceCommit", "provenance"}.isdisjoint(_keys(body))
    shas = [[_sha(answer.content) for answer in answers] for answers in (first, again, restarted)]
    assert shas[0] == shas[1] == shas[2]
    assert shas[0][0] != shas[0][1]


async def test_the_upload_header_carries_the_commit_read_when_the_server_started(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """만든 커밋은 측정 서버를 띄울 때 한 번 읽은 checkout 의 커밋 id(git 출력의 줄바꿈은 뗀다)와 더러움이다. 묶음을 만드는 코드는
    띄울 때 메모리에 올라간 코드라, 띄운 뒤 checkout 을 옮기거나 파일을 고쳐도 바뀌지 않는다 — 요청 때 git 에 다시 물으면 묶음을
    실제로 만든 코드와 다른 커밋이 붙는다. 그래서 띄운 뒤 git 상태가 바뀌어도 머리는 띄울 때 값(커밋·더러움 둘 다)이고 요청은 git
    을 부르지 않으며, 다시 띄우면 그때 상태를 읽는다. 진입점(`main`)이 서버를 돌리기 전에 읽어 앱에 넘긴다. 이 서버는 테스트 DB 에
    따로 붙어 테스트 트랜잭션의 방을 보지 못하지만, 만든 커밋은 출처 칸과 상관없다."""
    root, _, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    git = _use_git(monkeypatch)
    engines = _collect_engines(monkeypatch)
    database_url = os.environ["DATABASE_URL"]

    try:
        clean_app = _start(monkeypatch, root, database_url)
        reads = len(git.calls)
        git.commit, git.status = OTHER_COMMIT, DIRTY_STATUS
        async with _client(clean_app) as client:
            moved = await _header(client, run_id)
        dirty_app = _start(monkeypatch, root, database_url)
        git.commit, git.status = CLEAN_COMMIT, ""
        async with _client(dirty_app) as client:
            cleaned = await _header(client, run_id)
    finally:
        for made in engines:
            await made.dispose()

    assert reads > 0
    assert moved["sourceCommit"] == {"commit": CLEAN_COMMIT, "dirty": False}
    assert cleaned["sourceCommit"] == {"commit": OTHER_COMMIT, "dirty": True}
    assert len(git.calls) == 2 * reads


def test_dumping_the_schema_does_not_ask_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """만든 커밋을 읽는 것은 서버를 띄울 때뿐이다. 스키마 떨구기는 CI 러너에서도 커밋된 파일과 같은 바이트를 내야 해서 git·DB·런
    루트를 보지 않는다."""
    git = _use_git(monkeypatch)
    monkeypatch.setattr(chat_lab_server, "OPENAPI_PATH", tmp_path / "openapi.json")

    assert chat_lab_server.main(["--dump-openapi"]) == 0
    assert git.calls == []


async def test_files_git_does_not_track_leave_the_tree_clean(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """메인 checkout 에는 추적하지 않는 파일(스크린숏 png·임시 스크립트)이 늘 있다 — 그것까지 더러움으로 치면 거의 모든 묶음이 더러운
    트리로 올라가 표시가 뜻을 잃는다. 추적하지 않는 파일만 있으면 깨끗한 트리이고, 그 판정은 git 에 추적하지 않는 파일을 빼라고
    물어서 한다(`--untracked-files=no` — 출력을 걸러 내는 방식은 git 출력 모양에 묶인다). 추적하는 파일이 바뀌면 그대로 더럽다."""
    root, _, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    git = _use_git(monkeypatch)
    git.untracked = "?? screenshot.png\n?? scratch.py\n"
    untracked_app = _app(root, db_session)
    git.status = DIRTY_STATUS
    tracked_app = _app(root, db_session)

    async with _client(untracked_app) as client:
        untracked_only = await _header(client, run_id)
    async with _client(tracked_app) as client:
        tracked_change = await _header(client, run_id)

    assert untracked_only["sourceCommit"] == {"commit": CLEAN_COMMIT, "dirty": False}
    assert tracked_change["sourceCommit"] == {"commit": CLEAN_COMMIT, "dirty": True}
    status_calls = [call for call in git.calls if "status" in call]
    assert status_calls
    assert all("--untracked-files=no" in call for call in status_calls)


async def test_a_git_failure_at_startup_answers_503_to_the_upload_header_but_not_to_the_bundle(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """만든 커밋을 모르면 올리기 머리를 내지 않는다 — 서비스는 만든 커밋 없는 머리를 받지 않고, 빈 값이나 지어낸 값을 내면 어느
    코드로 낸 묶음인지 잃는다. 띄울 때 git 이 없거나(`OSError`), 측정 서버가 checkout 안에 있지 않거나(`CalledProcessError`), 커밋은
    읽었는데 트리 상태를 읽지 못했으면, 서버는 그대로 뜨고(목록·상세·묶음은 git 이 필요 없다) 그 사실을 들고 있다가 올리기 머리에
    503 `gitUnavailable` 로 답한다(DB 가 없는 503 과 갈라, 무엇을 고쳐야 하는지 보이게). 띄운 뒤 git 이 나아져도 다시 띄우기 전에는
    그대로다 — 메모리에 올라간 코드는 그대로이니."""
    root, _, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    git = _use_git(monkeypatch)
    engines = _collect_engines(monkeypatch)
    failures: list[dict[str, Exception]] = [
        {"rev-parse": FileNotFoundError(2, "No such file or directory", "git")},
        {"rev-parse": subprocess.CalledProcessError(128, ["git", "rev-parse", "HEAD"])},
        {"status": subprocess.CalledProcessError(128, ["git", "status"])},
    ]
    answers: list[tuple[httpx.Response, httpx.Response]] = []

    try:
        for failure in failures:
            git.failures = failure
            app = _start(monkeypatch, root, os.environ["DATABASE_URL"])
            git.failures = {}
            async with _client(app) as client:
                header = await client.post(f"/runs/{run_id}/upload-header", json={"exemptEmails": []})
                bundle = await client.get(f"/runs/{run_id}/bundle", params={"raw": "false"})
            answers.append((header, bundle))
    finally:
        for made in engines:
            await made.dispose()

    assert [(header.status_code, header.json()["reason"]) for header, _ in answers] == [(503, "gitUnavailable")] * 3
    assert all(set(header.json()) == {"detail", "reason"} for header, _ in answers)
    assert [bundle.status_code for _, bundle in answers] == [200] * 3


async def test_a_test_account_run_on_each_loopback_base_passes(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """meta 주소의 호스트가 127.0.0.1·localhost·::1 가운데 하나이고, 방이 이 DB 에 있으며 그 주인·작가가 테스트 계정이고, DB 에
    테스트 계정 밖 사용자가 없으면 모든 판정을 통과한다. 세 호스트는 측정 서버의 로컬 DB 가드가 받는 셋과 같다."""
    root, _, folder = await _drive(db_session, monkeypatch, tmp_path)
    _use_git(monkeypatch)
    run_ids = [_variant(root, folder, f"loopback-{n}", base=base) for n, base in enumerate(LOOPBACK_BASES)]

    async with _client(_app(root, db_session)) as client:
        answers = [await _provenance(client, run_id) for run_id in run_ids]

    assert answers == [PASSING] * len(LOOPBACK_BASES)


async def test_a_run_whose_base_is_not_loopback_fails_the_base_check(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """meta 주소의 호스트가 루프백이 아니면 로컬 측정 서버로 돈 런이 아니라 실패다 — 방·사용자 판정이 모두 통과해도. 테스트
    클라이언트 주소(`testserver` — 드라이버 장치가 적은 그대로), 같은 망의 다른 기기, 앞머리만 루프백 주소인 이름 모두."""
    root, _, folder = await _drive(db_session, monkeypatch, tmp_path)
    _use_git(monkeypatch)
    assert _meta(folder)["base"] == HARNESS_BASE
    run_ids = [
        _run_id(root, folder),
        *(_variant(root, folder, f"foreign-{n}", base=base) for n, base in enumerate(FOREIGN_BASES[1:])),
    ]

    async with _client(_app(root, db_session)) as client:
        answers = [await _provenance(client, run_id) for run_id in run_ids]

    assert answers == [{**PASSING, "passed": False, "baseLocal": False}] * len(FOREIGN_BASES)


async def test_a_meta_line_without_a_string_base_fails_the_base_check(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """meta 줄이 있으면 드라이버가 돈 런이라 주소를 적었어야 한다. 주소 칸이 없거나 문자열이 아니면(null·숫자·목록) 어디서 돈 런인지
    알 수 없어 실패 쪽으로 닫는다 — meta 줄이 아예 없는 프로브처럼 판정 없음으로 두면 주소 칸만 지운 묶음이 주소 판정을 건너뛴다.
    목록 안에 루프백 주소가 있어도 받지 않는다."""
    root, _, folder = await _drive(db_session, monkeypatch, tmp_path)
    _use_git(monkeypatch)

    def setting_base(value: object) -> Callable[[dict[str, Any]], None]:
        def edit(meta: dict[str, Any]) -> None:
            meta["base"] = value

        return edit

    odd_bases: list[object] = [None, 8793, [LOOPBACK_BASES[0]]]
    run_ids = [
        _variant_meta(root, folder, "no-base", lambda meta: meta.pop("base")),
        *(_variant_meta(root, folder, f"odd-{n}", setting_base(value)) for n, value in enumerate(odd_bases)),
    ]

    async with _client(_app(root, db_session)) as client:
        answers = [await _provenance(client, run_id) for run_id in run_ids]

    assert answers == [{**PASSING, "passed": False, "baseLocal": False}] * (1 + len(odd_bases))


async def test_the_test_domain_is_matched_without_case_and_a_suspended_account_still_counts(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """이메일 도메인은 대소문자를 가리지 않는다 — 주인·작가·다른 사용자의 `EXAMPLE.COM`·`Example.Com` 도 테스트 계정이다. 가리면
    대문자로 적힌 테스트 계정 하나 때문에 실패하고, 대소문자를 무시하더라도 `@` 까지 견줘야 `NOTEXAMPLE.COM` 이 테스트 계정으로
    읽히지 않는다. 정지 회원은 탈퇴가 아니라 계정과 이메일이 남아 있으므로 활성 사용자로 센다."""
    root, driven, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    _use_git(monkeypatch)
    room = await _room(db_session, driven.room_id)
    owner = await db_session.get(User, room.user_id)
    assert owner is not None
    owner.email = f"owner-{uuid.uuid4()}@EXAMPLE.COM"
    author = _make_user(email=f"author-{uuid.uuid4()}@Example.Com")
    db_session.add_all([author, _make_user(email=f"other-{uuid.uuid4()}@exAmple.cOm")])
    await db_session.flush()
    await _set_author(db_session, room, author)

    async with _client(_app(root, db_session)) as client:
        mixed_case = await _provenance(client, run_id)
        outsider = _make_user(email=f"outsider-{uuid.uuid4()}@{OUTSIDE_DOMAIN.upper()}")
        db_session.add(outsider)
        await db_session.flush()
        loud_outsider = await _provenance(client, run_id)
        outsider.suspended_at = datetime.now(UTC)
        await db_session.flush()
        suspended = await _provenance(client, run_id)

    assert mixed_case == PASSING
    counted = {**PASSING, "passed": False, "outsideUsers": 1}
    assert (loud_outsider, suspended) == (counted, counted)


async def test_the_test_domain_must_end_the_email(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """테스트 계정은 이메일이 `@example.com` 으로 끝나는 계정이다 — 그 글자가 가운데 있을 뿐인 주소(`@example.com.evil.org`,
    `@example.company.com`)는 테스트 계정이 아니다. 포함 여부로 견주면 남의 도메인 주소가 테스트 계정으로 읽혀 출처 판정을 통과한다.
    방 주인 판정(이메일을 꺼내 견주는 쪽)과 DB 사용자 수(DB 가 견주는 쪽) 둘 다 본다 — 주인을 예외로 넘기면 남는 바깥 사용자는
    `@example.company.com` 하나다."""
    root, driven, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    _use_git(monkeypatch)
    room = await _room(db_session, driven.room_id)
    author = _make_user()
    db_session.add_all([author, _make_user(email=f"x-{uuid.uuid4()}@example.company.com")])
    await db_session.flush()
    await _set_author(db_session, room, author)
    owner = await db_session.get(User, room.user_id)
    assert owner is not None
    owner.email = f"owner-{uuid.uuid4()}@example.com.evil.org"
    await db_session.flush()

    async with _client(_app(root, db_session)) as client:
        counted = await _provenance(client, run_id)
        owner_exempted = await _provenance(client, run_id, [owner.email])

    failing_owner = {**PASSING, "passed": False, "ownerInExampleDomain": False}
    assert counted == {**failing_owner, "outsideUsers": 2}
    assert owner_exempted == {**failing_owner, "outsideUsers": 1, "exemptedUsers": 1}


async def test_a_room_missing_from_this_database_fails_and_a_probe_without_meta_is_judged_by_its_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """방 id 가 이 DB 에 없으면 다른 DB 에서 돈 런이라 실패다 — 주인을 확인할 수 없고(실패) 작가는 알 수 없다(없음). meta 줄이 없는
    프로브 묶음은 주소 판정을 하지 않고(없음) 방 판정으로 간다: 방이 있으면 통과, 없으면 실패."""
    root, driven, folder = await _drive(db_session, monkeypatch, tmp_path)
    _use_git(monkeypatch)
    stranger = (driven.room_id, uuid.uuid4())
    run_ids = {
        "missing": _variant(root, folder, "missing", base=LOOPBACK_BASES[0], rooms=stranger),
        "probe": _variant(root, folder, "probe", base=None),
        "probe-missing": _variant(root, folder, "probe-missing", base=None, rooms=stranger),
    }

    async with _client(_app(root, db_session)) as client:
        answers = {name: await _provenance(client, run_id) for name, run_id in run_ids.items()}

    missing = {
        **PASSING,
        "passed": False,
        "roomFound": False,
        "ownerInExampleDomain": False,
        "authorInExampleDomain": None,
    }
    assert answers == {
        "missing": missing,
        "probe": {**PASSING, "baseLocal": None},
        "probe-missing": {**missing, "baseLocal": None},
    }


async def test_a_room_whose_owner_is_outside_the_test_domain_fails_even_when_exempted(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """방 주인이 테스트 계정이 아니면 실제 회원의 대화일 수 있어 실패다. 예외 이메일은 DB 사용자 수에서만 빼는 것이라 주인 판정을
    넘기지 못한다 — 예외로 넘기면 사용자 수만 0 이 되고 예외 수가 1 이 된다. 작가는 따로 둔 테스트 계정이라 경고가 없다."""
    root, driven, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    _use_git(monkeypatch)
    room = await _room(db_session, driven.room_id)
    author = _make_user()
    db_session.add(author)
    await db_session.flush()
    await _set_author(db_session, room, author)
    owner_email = await _move_owner_outside(db_session, room)

    async with _client(_app(root, db_session)) as client:
        counted = await _provenance(client, run_id)
        exempted = await _provenance(client, run_id, [owner_email])

    assert counted == {**PASSING, "passed": False, "ownerInExampleDomain": False, "outsideUsers": 1}
    assert exempted == {**PASSING, "passed": False, "ownerInExampleDomain": False, "exemptedUsers": 1}


async def test_an_active_account_outside_the_test_domain_fails_until_it_is_withdrawn_or_exempted(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """탈퇴하지 않은 테스트 계정 밖 사용자가 DB 에 하나라도 있으면 실제 회원이 있는 DB 일 수 있어 실패다(방과 상관없이).
    - 도메인은 `@` 까지 견준다 — `notexample.com` 은 테스트 계정이 아니다.
    - 예외 이메일로 넘기면 그 사용자를 세지 않고 예외 수로 센다. 예외 수는 목록 길이가 아니라 실제로 뺀 사용자 수다 — DB 에 없는
      주소만 넘기면 아무것도 빠지지 않는다.
    - 탈퇴한 사용자는 세지 않는다. 판정은 이메일 모양이 아니라 탈퇴 칸(`deleted_at`)으로 한다 — 탈퇴 처리는 이메일을
      `withdrawn:{id}` 로 바꾸지만, 바꾸기 전 이메일이어도 탈퇴 칸이 차 있으면 세지 않는다."""
    root, _, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    _use_git(monkeypatch)
    outsider = await _outside_user(db_session, "outsider")
    email = outsider.email
    nowhere = f"nobody-{uuid.uuid4()}@{OUTSIDE_DOMAIN}"

    async with _client(_app(root, db_session)) as client:
        active = await _provenance(client, run_id)
        unmatched = await _provenance(client, run_id, [nowhere])
        exempted = await _provenance(client, run_id, [email, nowhere])
        outsider.deleted_at = datetime.now(UTC)
        await db_session.flush()
        withdrawing = await _provenance(client, run_id)
        outsider.email = f"withdrawn:{outsider.id}"
        await db_session.flush()
        withdrawn = await _provenance(client, run_id)

    counted = {**PASSING, "passed": False, "outsideUsers": 1}
    assert (active, unmatched) == (counted, counted)
    assert exempted == {**PASSING, "exemptedUsers": 1}
    assert (withdrawing, withdrawn) == (PASSING, PASSING)


async def test_an_author_outside_the_test_domain_only_warns(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """작품 작가가 테스트 계정이 아니면 경고만 한다(통과는 막지 않는다) — 실제 회원의 작품을 테스트 계정으로 플레이한 런은 올릴 수
    있지만 알고 올려야 한다. 작가가 탈퇴하지 않은 회원이면 DB 사용자 수에도 걸려 예외 이메일로 넘긴다(로컬에서 구글 로그인을 써 본
    회원의 작품이 그 꼴이다). 예외로 넘겨도 경고는 남고, 작가가 탈퇴해 사용자 수에 걸리지 않아도 경고는 남는다."""
    root, driven, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    _use_git(monkeypatch)
    room = await _room(db_session, driven.room_id)
    author = await _outside_user(db_session, "author")
    await _set_author(db_session, room, author)

    async with _client(_app(root, db_session)) as client:
        exempted = await _provenance(client, run_id, [author.email])
        author.deleted_at = datetime.now(UTC)
        author.email = f"withdrawn:{author.id}"
        await db_session.flush()
        withdrawn = await _provenance(client, run_id)

    assert exempted == {**PASSING, "exemptedUsers": 1, "authorInExampleDomain": False}
    assert withdrawn == {**PASSING, "authorInExampleDomain": False}


async def test_exempt_emails_match_users_without_case(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """예외 이메일은 대소문자를 가리지 않고 사용자와 맞춘다 — 도메인 판정과 같다. 손으로 옮겨 적은 주소의 대소문자가 DB 와 다르다고
    예외가 말없이 빠지면 출처가 실패하고, 그 까닭이 응답에 보이지 않는다(이메일은 싣지 않는다). DB 에 소문자로 든 주소를 대문자로
    넘기는 쪽과, 대소문자가 섞여 든 주소를 소문자로 넘기는 쪽 둘 다 빠진다."""
    root, _, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    _use_git(monkeypatch)
    stored_lower = _make_user(email=f"outside-a-{uuid.uuid4()}@example.org")
    stored_mixed = _make_user(email=f"Outside-B-{uuid.uuid4()}@Example.ORG")
    db_session.add_all([stored_lower, stored_mixed])
    await db_session.flush()

    async with _client(_app(root, db_session)) as client:
        provenance = await _provenance(client, run_id, [stored_lower.email.upper(), stored_mixed.email.lower()])

    assert provenance == {**PASSING, "exemptedUsers": 2}


async def test_exempt_emails_are_matched_without_surrounding_spaces(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """손으로 붙여 넣은 예외 이메일의 앞뒤 공백은 떼고 맞춘다 — 공백 하나로 예외가 말없이 빠지면 출처가 실패하는데, 응답에는 이메일을
    싣지 않아 그 까닭이 보이지 않는다. 대소문자 무시와 함께 걸린다."""
    root, _, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    _use_git(monkeypatch)
    stored = _make_user(email=f"friend-{uuid.uuid4()}@example.org")
    db_session.add(stored)
    await db_session.flush()
    pasted = " " + stored.email.replace("friend", "Friend").replace("example.org", "Example.org") + " "

    async with _client(_app(root, db_session)) as client:
        provenance = await _provenance(client, run_id, [pasted])

    assert provenance == {**PASSING, "exemptedUsers": 1}


async def test_exempting_a_test_account_or_a_withdrawn_account_removes_nobody(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """예외 수는 테스트 계정 밖 활성 사용자 가운데 실제로 뺀 수다. 테스트 계정(방 주인, 대소문자를 바꾼 것 포함)이나 탈퇴한 사용자
    (이메일이 남은 것, 자리표시자로 바뀐 것)를 넘기면 원래 세지 않던 사용자라 아무도 빠지지 않는다 — 예외 수가 늘면 쓸데없는 예외를
    넘긴 것이 "예외로 넘긴 사용자가 있다"로 읽힌다."""
    root, driven, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    _use_git(monkeypatch)
    owner = await db_session.get(User, (await _room(db_session, driven.room_id)).user_id)
    assert owner is not None
    kept_email = await _outside_user(db_session, "gone")
    placeholder = await _outside_user(db_session, "placeholder")
    kept_email.deleted_at = placeholder.deleted_at = datetime.now(UTC)
    placeholder.email = f"withdrawn:{placeholder.id}"
    await db_session.flush()
    exempt = [owner.email, owner.email.upper(), kept_email.email, placeholder.email]

    async with _client(_app(root, db_session)) as client:
        provenance = await _provenance(client, run_id, exempt)

    assert provenance == PASSING


async def test_a_database_error_during_the_provenance_check_answers_503_without_its_text_or_any_email(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """출처 조회가 DB 오류로 끝나면 503(`dbUnavailable`)이다. 응답 글에도 서버 로그(경고 이상 — 서버가 실제로 남기는 수준)에도
    예외 원문을 싣지 않는다 — SQLAlchemy 오류 글에는 실행한 SQL 과 바인드 인자가 들어가고, 사용자 수 쿼리의 바인드 인자에는 예외
    이메일이 있다. 오류는 이 테스트 트랜잭션 안에서 탈퇴 칸의 이름을 바꿔 그 쿼리가 실제로 실패하게 만든다(방 쿼리는 그 칸을 읽지
    않아 지나간다)."""
    root, _, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    _use_git(monkeypatch)
    exempt = [(await _outside_user(db_session, "outsider")).email]
    await db_session.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    await db_session.execute(sa.text("ALTER TABLE users RENAME COLUMN deleted_at TO deleted_at_renamed"))
    caplog.set_level(logging.WARNING)
    caplog.clear()

    async with _client(_app(root, db_session)) as client:
        answer = await client.post(f"/runs/{run_id}/upload-header", json={"exemptEmails": exempt})

    assert (answer.status_code, answer.json()["reason"]) == (503, "dbUnavailable")
    for text in (answer.text, caplog.text):
        assert EMAIL_SHAPE.search(text) is None
        assert all(email not in text for email in exempt)
        assert "deleted_at" not in text
        assert "parameters" not in text


async def test_a_driver_interface_error_during_the_provenance_check_answers_503_without_its_text(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """드라이버(asyncpg)의 인터페이스 오류(끊긴 연결·쓸 수 없는 연결)도 SQLAlchemy 가 감싸지 않은 채 올 수 있다 — DB 를 쓸 수 없는
    것이라 503(`dbUnavailable`)이고, 상세에는 예외 이름만 싣는다. 출처 조회의 첫 쿼리가 그 오류를 내게 하고, 오류 글에 넘긴 예외
    이메일을 넣어 원문이 새는지 본다. 턴 기록 내보내기도 같은 예외 목록을 쓴다."""
    root, _, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    _use_git(monkeypatch)
    email = f"friend-{uuid.uuid4()}@{OUTSIDE_DOMAIN}"
    app = _app(root, db_session)

    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise asyncpg.InterfaceError(f"connection is closed while asking about {email}")

    monkeypatch.setattr(db_session, "execute", broken)

    async with _client(app) as client:
        answer = await client.post(f"/runs/{run_id}/upload-header", json={"exemptEmails": [email]})

    assert (answer.status_code, answer.json()["reason"]) == (503, "dbUnavailable")
    assert email not in answer.text
    assert "connection is closed" not in answer.text
    assert EMAIL_SHAPE.search(answer.text) is None


async def test_a_bundle_whose_room_id_is_not_a_uuid_is_refused_as_unsupported_before_any_check(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """방 id 가 uuid 가 아닌 로그(손으로 고쳐 쓴 꼴)는 묶음을 열 때 결합이 거부한다. 올리기 머리도 통째 묶음과 같은 422 지원 안
    함이다 — 열지 않는 묶음은 어느 경로에서나 같은 상태 코드로 알린다. 출처 조회와 git 에 닿기 전에 거부한다."""
    root, driven, folder = await _local_run(db_session, monkeypatch, tmp_path)
    git = _use_git(monkeypatch)
    target = folder.parent / "not-uuid"
    shutil.copytree(folder, target)
    for file_name in RUN_FILES:
        path = target / file_name
        path.write_text(
            path.read_text(encoding="utf-8").replace(str(driven.room_id), "room-not-a-uuid"), encoding="utf-8"
        )
    run_id = _run_id(root, target)
    app = _app(root, db_session)
    calls = len(git.calls)

    async with _client(app) as client:
        header = await client.post(f"/runs/{run_id}/upload-header", json={"exemptEmails": []})
        bundle = await client.get(f"/runs/{run_id}/bundle", params={"raw": "false"})

    assert [(answer.status_code, answer.json()["reason"]) for answer in (header, bundle)] == [(422, "unsupported")] * 2
    assert len(git.calls) == calls


async def test_no_email_reaches_the_upload_header_or_the_bundle(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """출처 칸은 불·수만 싣는다 — 서비스로 가는 응답에 이메일이 실리면 개인정보가 서버로 나간다. 주인·작가·바깥 사용자가 모두 테스트
    계정 밖 이메일을 갖고 예외 목록에도 이메일이 있어 판정마다 답이 갈리는 상태에서, 올리기 머리와 두 묶음 응답 어디에도 그
    이메일들과 이메일 꼴 글자가 없다."""
    root, driven, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    _use_git(monkeypatch)
    room = await _room(db_session, driven.room_id)
    owner_email = await _move_owner_outside(db_session, room)
    author = await _outside_user(db_session, "author")
    await _set_author(db_session, room, author)
    outsider = await _outside_user(db_session, "outsider")
    emails = [owner_email, author.email, outsider.email]

    async with _client(_app(root, db_session)) as client:
        header = await client.post(f"/runs/{run_id}/upload-header", json={"exemptEmails": emails[:2]})
        bundles = [await client.get(f"/runs/{run_id}/bundle", params={"raw": raw}) for raw in ("true", "false")]

    assert [answer.status_code for answer in (header, *bundles)] == [200] * 3
    assert header.json()["provenance"] == {
        **PASSING,
        "passed": False,
        "ownerInExampleDomain": False,
        "outsideUsers": 1,
        "exemptedUsers": 2,
        "authorInExampleDomain": False,
    }
    for answer in (header, *bundles):
        assert EMAIL_SHAPE.search(answer.text) is None
        assert all(email not in answer.text for email in emails)


async def test_the_upload_header_refuses_what_the_server_cannot_judge(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """판정할 수 없으면 출처 칸을 내지 않고 거부한다 — 서비스는 머리 없는 묶음을 받지 않는다.
    - 옛 형식 묶음(턴 줄에 방 id 가 없다)은 다른 경로와 같은 422 지원 안 함이다.
    - 없는 묶음은 404, JSON 이 아닌 본문은 라우팅 전에 415, 본문 모양이 틀리면 요청 검증 422(`reason` 없음).
    - DB 를 설정하지 않았거나 닿지 않으면 사용자 수를 셀 수 없어 503 이다."""
    root, _, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    _use_git(monkeypatch)
    legacy = folder.parent / "legacy"
    shutil.copytree(folder, legacy)
    records = _records(legacy / DRIVER_LOG)
    for record in records:
        if record.get("kind") == "turn":
            record.pop("roomId")
    _write_records(legacy / DRIVER_LOG, records)
    path = f"/runs/{run_id}/upload-header"

    async with _client(_app(root, db_session)) as client:
        refused = [
            await client.post(f"/runs/{_run_id(root, legacy)}/upload-header", json={"exemptEmails": []}),
            await client.post(
                f"/runs/{encode_run_id(root, folder / 'other.jsonl')}/upload-header", json={"exemptEmails": []}
            ),
            await client.post(path, content=b'{"exemptEmails": []}', headers={"Content-Type": "text/plain"}),
        ]
        malformed = await client.post(path, json={"exemptEmails": 3})
    unjudged = []
    for database_url in (None, UNREACHABLE_DB):
        async with _client(create_app(root=root, database_url=database_url, source_commit=_startup_commit())) as client:
            unjudged.append(await client.post(path, json={"exemptEmails": []}))

    assert [(answer.status_code, answer.json()["reason"]) for answer in refused] == [
        (422, "unsupported"),
        (404, "notFound"),
        (415, "notJson"),
    ]
    assert malformed.status_code == 422
    assert "reason" not in malformed.json() and isinstance(malformed.json()["detail"], list)
    assert [(answer.status_code, answer.json()["reason"]) for answer in unjudged] == [(503, "dbUnavailable")] * 2


async def test_request_validation_errors_do_not_echo_the_request_body(tmp_path: Path) -> None:
    """요청 모양이 틀린 422(FastAPI 기본)는 상세의 `input` 에 받은 값을, `ctx` 에 검증 맥락을 그대로 되돌린다 — 올리기 머리에 넘긴
    예외 이메일이 응답으로 되돌아 나온다. 측정 서버의 422 상세는 어디가(`loc`) 왜(`msg`·`type`) 틀렸는지만 싣는다. 웹은 이 상세의
    칸을 읽지 않는다(`reason` 이 없으면 거부 본문이 아니라고 보고 오류 글을 쓴다). 본문이 JSON 으로 읽히지 않는 422 도 같은 모양이다."""
    app = create_app(root=tmp_path, database_url=None)
    email = "friend@gmail.com"

    async with _client(app) as client:
        answers = [
            await client.post("/runs/x/upload-header", json={"exemptEmails": email}),
            await client.post("/runs/x/upload-header", json={"exempt": [email]}),
            await client.post("/runs/x/export-turns", json={"force": email}),
            await client.post(
                "/runs/x/upload-header",
                content=f'{{"exemptEmails": ["{email}"'.encode(),
                headers={"Content-Type": "application/json"},
            ),
        ]

    assert [answer.status_code for answer in answers] == [422] * 4
    for answer in answers:
        body = answer.json()
        assert "reason" not in body
        assert body["detail"]
        assert all({"loc", "msg", "type"} <= set(item) for item in body["detail"])
        assert all("input" not in item and not item.get("ctx") for item in body["detail"])
        assert email not in answer.text
        assert EMAIL_SHAPE.search(answer.text) is None


async def test_the_provenance_check_connects_only_through_the_one_guarded_local_url_and_builds_no_llm_client(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """측정 서버는 DB 주소 하나만 받고, 그 주소가 로컬이 아니면 앱을 만들지 않는다 — 엔진도 만들지 않으므로 접속 전에 거부된다.
    로컬 주소로 띄운 서버는 묶음 요청(정적 내보내기가 받는 것)에는 엔진을 만들지 않고, 출처 조회 때 그 주소로 엔진 하나를 만든다.
    출처 조회는 LLM 클라이언트를 만들지 않고 Redis 에 접속하지 않는다. 그 엔진은 다른 연결이라 이 테스트 트랜잭션의 방을 보지
    못해 방 없음으로 답한다. 감시는 런을 만든 뒤에 건다 — 런을 만드는 테스트 앱은 Redis·가짜 LLM 을 쓴다."""
    root, _, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    _use_git(monkeypatch)
    seen = _count_llm_and_redis(monkeypatch)
    engines = _collect_engines(monkeypatch)

    for url in NON_LOCAL_DATABASES:
        with pytest.raises(SystemExit):
            create_app(root=root, database_url=url)
    assert engines == []
    local = os.environ["DATABASE_URL"]
    app = create_app(root=root, database_url=local, source_commit=_startup_commit())
    async with _client(app) as client:
        bundles = [await client.get(f"/runs/{run_id}/bundle", params={"raw": raw}) for raw in ("true", "false")]
        assert engines == []
        header = await client.post(f"/runs/{run_id}/upload-header", json={"exemptEmails": []})

    try:
        assert [answer.status_code for answer in (*bundles, header)] == [200] * 3
        assert header.json()["provenance"]["roomFound"] is False
        assert len(engines) == 1
        assert engines[0].url.render_as_string(hide_password=False) == make_url(local).render_as_string(
            hide_password=False
        )
        assert seen == Counter()
    finally:
        for made in engines:
            await made.dispose()


async def test_a_database_that_refuses_the_login_answers_503_on_both_database_paths(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """로컬 DB 의 계정이나 DB 이름이 틀리면 접속 단계에서 드라이버(asyncpg)가 자기 오류를 낸다 — SQLAlchemy 가 감싸지 않아
    SQLAlchemy 오류만 잡으면 500 text/plain 이 되고, 웹은 거부 종류를 읽지 못한다. 그것도 DB 를 쓸 수 없는 것이라 출처 조회와 턴
    기록 내보내기 둘 다 503(`dbUnavailable`)이고 파일은 생기지 않는다. 응답에는 예외 원문도 이메일도 없다 — 원문에는 접속 주소의
    계정·DB 이름이 들고, 출처 조회의 오류에는 예외 이메일이 들 수 있다. 없는 계정은 인증 방식과 상관없이 거부된다."""
    root, _, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    _use_git(monkeypatch)
    engines = _collect_engines(monkeypatch)
    local = make_url(os.environ["DATABASE_URL"])
    wrong = [local.set(username="chat_lab_no_such_user"), local.set(database="chat_lab_no_such_database")]
    exempt = [f"friend-{uuid.uuid4()}@{OUTSIDE_DOMAIN}"]
    answers: list[httpx.Response] = []

    try:
        for url in wrong:
            app = create_app(
                root=root, database_url=url.render_as_string(hide_password=False), source_commit=_startup_commit()
            )
            async with _client(app) as client:
                answers.append(await client.post(f"/runs/{run_id}/upload-header", json={"exemptEmails": exempt}))
                answers.append(await client.post(f"/runs/{run_id}/export-turns", json={"force": False}))
    finally:
        for made in engines:
            await made.dispose()

    assert [answer.status_code for answer in answers] == [503] * 4
    assert [answer.json()["reason"] for answer in answers] == ["dbUnavailable"] * 4
    for answer in answers:
        assert "chat_lab_no_such" not in answer.text
        assert "does not exist" not in answer.text
        assert "authentication" not in answer.text
        assert EMAIL_SHAPE.search(answer.text) is None
    assert not (folder / CHAT_TURNS_NAME).exists()


async def test_the_provenance_check_reads_only_named_columns_and_runs_on_a_database_without_newer_columns(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """올려 둘 대표 런의 DB 는 복원한 옛 덤프라 지금 모델보다 칸이 적다(방의 모델·잊기 세대, 작품의 소설 판매·허락·파생 소설 보이기·
    편집 시각, 사용자의 본인인증 두 칸). 출처 조회가 방·작품·사용자 엔티티를 통째로 고르면 그런 DB 에서 없는 칸 오류가 난다. 그
    칸들을 이 테스트 트랜잭션 안에서 지운 DB 에서도 출처 조회가 통과해야 하고, 고르는 칸은 판정에 쓰는 이름뿐이어야 한다 — 앞으로
    더해질 칸도 옛 DB 에는 없다. 지운 칸은 테스트가 끝나며 트랜잭션과 함께 되돌아온다."""
    root, _, folder = await _local_run(db_session, monkeypatch, tmp_path)
    run_id = _run_id(root, folder)
    _use_git(monkeypatch)
    await db_session.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table, columns in NEWER_COLUMNS.items():
        await db_session.execute(sa.text(f"ALTER TABLE {table} " + ", ".join(f"DROP COLUMN {c}" for c in columns)))

    with _statements() as statements:
        async with _client(_app(root, db_session)) as client:
            provenance = await _provenance(client, run_id)

    assert provenance == PASSING
    text = "\n".join(statements)
    assert all(re.search(rf"\b{table}\b", text) for table in READ_COLUMNS)
    for columns in NEWER_COLUMNS.values():
        assert not [column for column in columns if re.search(rf"\b{column}\b", text)]
    read: dict[str, set[str]] = {table: set() for table in READ_COLUMNS}
    for table, column in re.findall(r"\b(chat_rooms|contents|users)(?:_\d+)?\.(\w+)", text):
        read[table].add(column)
    assert all(read[table] <= READ_COLUMNS[table] for table in READ_COLUMNS), read
