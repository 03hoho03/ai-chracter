"""측정 드라이버 — 시뮬레이터(대화 에이전트)나 사람이 응답을 읽고 다음 말을 정해, 스토리 방에 한 번에 한 턴씩 보낸다.
남는 로그는 대화 품질 판정과 지난 턴 다시 생성(리플레이)의 입력이다.

    cd apps/api
    # 방 만들기: 오프닝·추천 답변·플레이가이드를 출력하고 방 고정값을 남긴다
    uv run --env-file .env python scripts/chat_play.py --base <url> --cred-file <f> --cookie-file <f> \\
        --log <run>/chat.jsonl --snapshot-log <run>/memory-snapshots.jsonl --content-id <uuid> [--setup 0]
    # 한 턴(--say 또는 --shortcut 중 하나)
    uv run --env-file .env python scripts/chat_play.py ... --room <id> --say "안녕하세요" [--tag <꼬리표>] \\
        [--set-note <노트 파일>] [--server-log <서버 로그>] [--stop-file <f>] [--pause-at 100,250] [--check-every 25]
    uv run --env-file .env python scripts/chat_play.py ... --room <id> --rebase "사람 구간 끝"   # 누적값 다시 잡기
    uv run --env-file .env python scripts/chat_play.py ... --room <id> --state                   # 상태만 출력(기록 안 함)

전제:
- 리플레이하려면 측정하는 동안 서버를 `PROMPT_DUMP_PATH` 를 켜고 띄운다. 리플레이는 그 턴에 서버가 실제로 쓴 프롬프트가
  덤프에 있고 다시 조립한 프롬프트가 그것과 바이트까지 같을 때만 호출하므로, 덤프 없이 잰 방은 리플레이할 수 없다.
- 드라이버는 `--env-file` 로 준 `DATABASE_URL` 의 DB 를 직접 읽는다(작품 버전 id·대화 프로필 본문·칸 이름은 API 에
  없다). 그 DB 가 로컬(localhost 류)이 아니면 네트워크 요청 전에 거부한다 — 실제 사용자 대화를 측정·생성 모델에 다시
  보내지 않기 위해서다. 그리고 그 DB 가 `--base` 서버의 DB 인지 방 행·프로필 id·턴 수·시작 설정 행으로 확인한다.
- 스토리 작품만 다룬다. 캐릭터 작품·방은 명시 오류로 거부한다(리플레이의 재현 검증이 스토리 대본만 덮는다).
- `--log` 가 있는 폴더가 곧 실행 폴더다. 턴 간격 스탬프(`.last_turn`)와 앱 429 의 재시도 시각(`.retry_at`)을 그 옆에
  둔다 — 프로세스가 턴마다 새로 뜨므로 메모리에 둘 수 없다. 방 하나를 한 폴더에서 잰다.
- `--base` 는 필수다 — 기본값을 두면 빠뜨렸을 때 공유 dev 서버에 방이 생긴다.

로그인: 로그인 요청은 성공·실패 무관하게 이메일당 15분 상한에 세지고 면제 계정도 예외가 아니다. 그래서 실행마다
로그인하지 않고 세션 쿠키 **값**만 저장소 밖 0600 파일에 두고 다시 쓴다. 도메인 없이 넣어야 `--base` 의 호스트 표기가
바뀌어도 실린다. 401 이면 한 번 다시 로그인하고 같은 요청을 다시 보낸다(401 은 사용자 메시지 커밋 전에 난다). 상한 창
안에서 두 번째 로그인이 필요해지면 조용한 재로그인 반복이 상한을 다 쓰기 전에 멈춘다.

누적 상태: 턴마다 방 전체를 다시 받으면 메시지가 수백 개인 방에서 턴마다 수 MB 가 오간다. 스탯은 SSE `statChange`
의 새 값으로 덮어쓰고, 턴 수는 `done` 마다 +1, 엔딩은 `endingReached` 로 안다. 이 누적값은 프로세스마다 새로 뜨므로
`--log` 의 마지막 기준(오프닝·턴·재기준·대조 줄의 `roomAfter`)에서 읽는다. `--check-every` 턴마다 한 번 방을 조회해
대조하고 어긋나면 멈춘다. 유실 턴(생성 오류·연결 오류) 뒤에는 다음 실행이 먼저 조회로 기준을 다시 잡는다. 사람 턴·서버
재기동 뒤에는 `--rebase` 로 다시 잡는다. 턴 줄의 `clientTurn` 은 서버 턴 수 + 1 로, 프롬프트 덤프의 턴 번호와 같다 —
그래서 유실 턴과 그 재시도는 같은 번호이고, 유실 턴의 `reply` 는 비우고 받은 조각은 `partialReply` 에 둔다.

은폐: `--log` 는 시뮬레이터가 읽을 수 있다. 화면에 보이는 것만 남긴다 — 스탯 설명, 엔딩 판정문·규칙, 도달 전
에필로그, 단축어 프롬프트 원문, 대화 요약 본문, 대화 프로필 전문, 정지 이유는 넣지 않는다. 그런 것은 `--snapshot-log`
(시뮬레이터 읽기 금지 파일)에 둔다. 출력도 같다 — 기억은 노트만 보여 준다.

종료 코드: 0 정상(생성 오류·정책 경고로 유실된 턴 포함 — 출력에 이유가 나간다) · 1 그 밖의 HTTP 오류·턴 도중 연결
오류(턴 줄은 남고 다음 실행이 조회로 기준을 다시 잡는다) · 2 인증(401 재로그인 실패·403·자격 파일 거부·로그인 429·
상한 창 안 두 번째 로그인)·운영 DB·드라이버 DB 와 서버 불일치·스토리가 아닌 작품·방 고정값 기록이 없는 옛 로그
(`--rebase` 로 다시 기록), 인자 오류도 argparse 가 2 · 3 엔딩 도달 · 4 앱 버스트 429(같은 명령을 다시 실행하면
retryAfterSeconds 만큼 기다린다) · 5 Gemini 한도(`--server-log` 를 줬을 때, 그 로그에 이 방의 429) · 6 턴 진행 중
409 · 7 클로버 429 · 8 누적값과 조회값 불일치 · 9 노트가 길이 상한을 넘음 · 10 일시 정지(정지 파일 · `--pause-at`).
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api.chat.schemas import MEMORY_NOTE_MAX_LENGTH
from api.chat.turn_lock import TURN_IN_PROGRESS_CODE
from api.content.author_macros import expand_author_macros
from api.content.media_tags import media_tag_refs
from api.core.config import settings
from api.core.rate_limit import LOGIN_EMAIL_WINDOW_SECONDS
from api.db.models.chat import ChatRoom
from api.db.models.story import MediaBookCell, MediaBookPerson, MediaBookScene
from replay.local_db import ensure_local_database
from replay.room_fixed import RoomFixed, load_room_fixed

# 턴 사이 최소 간격(초). 호출할 때 모듈 값을 읽으므로 테스트가 0 으로 바꿔 끌 수 있다.
MIN_GAP = 10.0
CLOVER_CODES = frozenset({"CLOVER_REQUIRED", "CLOVER_CONFIRM_REQUIRED"})
RATE_LIMIT_NOTICE = "측정 중단: 외부 한도 — 실행한 쪽에 보고"
PAUSE_NOTICE = "일시 정지 — 실행한 쪽에 보고"
# 서버 로그에서 Gemini 429 흔적. 예외 클래스 이름·Sentry 태그는 로그에 찍히지 않고, 생성·판정·요약 실패 줄이 예외
# 문자열(genai `APIError` 의 `"429 RESOURCE_EXHAUSTED. …"`)과 방 id 를 함께 싣는다. 429 본문이 JSON 이 아니면 SDK 가
# 상태 자리를 HTTP 사유 문구로 채워(`"429 Too Many Requests. …"`) RESOURCE_EXHAUSTED 가 빠지므로, 서버 클라이언트가
# 예외를 감싸는 접두(`… call failed: {예외}`) 바로 뒤의 상태 코드 429 도 본다. 맨 숫자 429 만으로는 보지 않는다 —
# 모든 줄 앞 시각의 밀리초(`…:43.429+0900`)와 사용량 줄의 토큰 수(`candidates_tokens=429`)가 같은 숫자가 된다.
# 접근 로그 줄은 앱이 낸 429(버스트·클로버)라 뺀다. Bedrock(Claude) 스로틀은 문구가 달라 이 패턴이 잡지 못한다.
_GEMINI_429 = re.compile(r"RESOURCE_EXHAUSTED|call failed: 429\b")
_ACCESS_LINE = re.compile(r'"[A-Z]+ \S+ HTTP/[0-9.]+" \d{3}')


class DriverExitError(Exception):
    """실행을 끝낼 종료 코드와 출력할 한 줄."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _repo_top() -> Path:
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=Path(__file__).parent, capture_output=True, text=True, check=True
    ).stdout.strip()
    return Path(top).resolve()


def _private_path(raw: str, what: str, *, must_exist: bool) -> Path:
    """자격·쿠키 파일은 저장소 밖 0600 이어야 한다. 메시지에는 경로만 — 내용은 내보내지 않는다."""
    path = Path(raw).expanduser().resolve()
    if path.is_relative_to(_repo_top()):
        raise DriverExitError(2, f"{what} 가 저장소 안에 있다: {path}")
    if not path.exists():
        if must_exist:
            raise DriverExitError(2, f"{what} 을 읽을 수 없다: {path}")
        return path
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode != 0o600:
        raise DriverExitError(2, f"{what} 권한이 0600 이 아니다({mode:o}): {path}")
    return path


def _load_cred(raw: str) -> tuple[str, str]:
    path = _private_path(raw, "--cred-file", must_exist=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        email, password = data["email"], data["password"]
    except (OSError, ValueError, KeyError, TypeError):
        raise DriverExitError(2, f"--cred-file 은 email·password 키를 가진 JSON 이어야 한다: {path}") from None
    if not (isinstance(email, str) and isinstance(password, str)):
        raise DriverExitError(2, f"--cred-file 의 email·password 는 문자열이어야 한다: {path}")
    return email, password


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, 0o600)


def _append(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()


def _records(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ── 로그인·쿠키 ─────────────────────────────────────────────────────────────


class Session:
    """세션 쿠키를 다시 쓰는 클라이언트. 로그인 기록(`login`·`relogin`)은 `--log` 에 남겨 상한 창 안 두 번째 로그인을
    다음 실행에서도 알아본다."""

    def __init__(
        self, base: str, cred_file: str, cookie_file: str, log: Path, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._cred_file = cred_file
        self._cookie_path = _private_path(cookie_file, "--cookie-file", must_exist=False)
        self._log = log
        self.client = httpx.Client(base_url=base, timeout=300, transport=transport)
        value = self._cookie_path.read_text(encoding="utf-8").strip() if self._cookie_path.exists() else ""
        if value:
            self.client.cookies.set(settings.session_cookie_name, value)
        else:
            self._login("login")

    def _login(self, kind: str) -> None:
        now = time.time()
        recent = [
            r
            for r in _records(self._log)
            if r.get("kind") in ("login", "relogin") and now - float(r.get("epoch", 0)) < LOGIN_EMAIL_WINDOW_SECONDS
        ]
        if recent:
            raise DriverExitError(
                2, f"로그인 상한 창({LOGIN_EMAIL_WINDOW_SECONDS}초) 안에서 두 번째 로그인이 필요해 멈춘다"
            )
        email, password = _load_cred(self._cred_file)
        self.client.cookies.clear()
        response = self.client.post("/auth/login", json={"email": email, "password": password})
        _append(self._log, {"kind": kind, "at": _now(), "epoch": now, "http": response.status_code})
        if response.status_code == 429:
            raise DriverExitError(2, f"로그인 429 {_detail_code(response)}")
        if response.status_code in (401, 403):
            raise DriverExitError(2, f"로그인 거부 HTTP {response.status_code}")
        if response.status_code >= 400:
            raise DriverExitError(1, f"로그인 실패 HTTP {response.status_code}")
        value = response.cookies.get(settings.session_cookie_name)
        if not value:
            raise DriverExitError(2, "로그인 응답에 세션 쿠키가 없다")
        _write_private(self._cookie_path, value)
        self.client.cookies.clear()
        self.client.cookies.set(settings.session_cookie_name, value)

    def relogin(self) -> None:
        self._login("relogin")

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        response = self.client.request(method, url, **kwargs)
        if response.status_code == 401:
            self.relogin()
            response = self.client.request(method, url, **kwargs)
        if response.status_code in (401, 403):
            raise DriverExitError(2, f"HTTP {response.status_code}: {response.text[:300]}")
        return response


def _detail(response: httpx.Response) -> dict[str, Any]:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return {}
    return detail if isinstance(detail, dict) else {}


def _detail_code(response: httpx.Response) -> str | None:
    code = _detail(response).get("code")
    return code if isinstance(code, str) else None


def _ok(response: httpx.Response, what: str) -> dict[str, Any]:
    if response.status_code >= 400:
        raise DriverExitError(1, f"{what} HTTP {response.status_code}: {response.text[:300]}")
    body: dict[str, Any] = response.json()
    return body


# ── 드라이버 DB (방 고정값 · 칸 이름) ────────────────────────────────────────


@dataclass(frozen=True)
class DbRoom:
    """드라이버가 자기 DB 에서 읽는 방 — 고정값, 지금 턴 수(서버와 같은 DB 인지 보는 데 쓴다), 방 버전의 칸 이름 표."""

    fixed: RoomFixed
    turn_count: int
    # 칸 entity_id 문자열 → "인물/장면". API 는 칸 이름을 주지 않고 화면 글의 태그는 칸 id 형태라 DB 에서 찾는다.
    cell_labels: dict[str, str]


DbRoomReader = Callable[[str], DbRoom | None]


async def read_db_room(db: AsyncSession, room_id: uuid.UUID) -> DbRoom | None:
    """방이 없으면 None. 칸 이름은 방이 고정한 버전의 미디어 북에서 읽는다 — 화면도 그 버전의 칸으로 태그를 푼다."""
    fixed = await load_room_fixed(db, room_id)
    if fixed is None:
        return None
    turn_count = await db.scalar(select(ChatRoom.turn_count).where(ChatRoom.id == room_id))
    assert turn_count is not None
    version = fixed.content_version_id
    people = dict(
        (
            await db.execute(
                select(MediaBookPerson.entity_id, MediaBookPerson.name).where(
                    MediaBookPerson.content_version_id == version
                )
            )
        )
        .tuples()
        .all()
    )
    scenes = dict(
        (
            await db.execute(
                select(MediaBookScene.entity_id, MediaBookScene.name).where(MediaBookScene.content_version_id == version)
            )
        )
        .tuples()
        .all()
    )
    cells = (
        await db.execute(
            select(MediaBookCell.entity_id, MediaBookCell.person_entity_id, MediaBookCell.scene_entity_id).where(
                MediaBookCell.content_version_id == version
            )
        )
    ).tuples()
    labels = {str(cell): f"{people.get(person, '?')}/{scenes.get(scene, '?')}" for cell, person, scene in cells}
    return DbRoom(fixed=fixed, turn_count=turn_count, cell_labels=labels)


async def _read_db_room_with_own_engine(room_id: str) -> DbRoom | None:
    # 전역 엔진(`api.db.session.engine`)을 쓰지 않는다 — 그 풀은 처음 쓴 이벤트 루프에 묶여, 같은 프로세스에서
    # 다른 루프가 쓰면 깨진다. 실행마다 새 루프(`asyncio.run`)를 여는 이 도구는 연결을 남기지 않는 엔진을 따로 연다.
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine) as db:
            return await read_db_room(db, uuid.UUID(room_id))
    finally:
        await engine.dispose()


def default_db_reader() -> DbRoomReader:
    """`settings.database_url`(실행할 때 `--env-file` 로 준 DB)을 읽는 함수. 만들 때 그 DB 호스트가 로컬이 아니면
    거부한다 — 로그인·방 만들기 같은 네트워크 요청보다 먼저다. 이 거부는 DB 호스트만 본다. `--base` 가 다른 서버(운영
    포함)이고 DB 만 로컬이면 여기서는 통과해 방이 만들어지고, 그 뒤 드라이버 DB 와 서버가 같은지 보는 확인에서 기록 전에
    멈춘다(턴은 보내지 않는다)."""
    try:
        ensure_local_database(settings.database_url, tool="chat_play.py")
    except SystemExit as refused:
        raise DriverExitError(2, str(refused)) from None

    def read(room_id: str) -> DbRoom | None:
        return asyncio.run(_read_db_room_with_own_engine(room_id))

    return read


# ── 화면 글 (작가 글 이름 치환 · 그림 태그) ──────────────────────────────────


def render_author_text(text: str, user_name: str, labels: dict[str, str]) -> str:
    """작가 글(오프닝·추천 답변·플레이가이드·에필로그)을 화면과 같게 바꾼다. 칸 태그는 그림 대신 `[그림: 인물/장면]` —
    방 버전에 없는 칸은 화면처럼 지운다. 태그를 먼저 바꾸고 이름을 바꾼다(서버 빌더와 같은 순서). 모델 응답은 화면이
    바꾸지 않으므로 이 함수를 지나지 않는다. 스토리 방만 다루므로 `{{char}}` 이름은 없다."""
    for cell_id in media_tag_refs(text):
        label = labels.get(str(cell_id))
        text = text.replace("{{img::" + str(cell_id) + "}}", f"[그림: {label}]" if label else "")
    return expand_author_macros(text, user_name=user_name, char_name=None)


def cell_label(image_id: str | None, labels: dict[str, str]) -> str | None:
    if not image_id:
        return None
    return labels.get(image_id, "(방 버전에 없는 칸)")


# ── 방 정적 정보 · 누적 상태 ─────────────────────────────────────────────────


def _stat_defs(room: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = room.get("contentSnapshot") or {}
    return [{"id": s["id"], "name": s["name"], "unit": s.get("unit") or ""} for s in snapshot.get("stats", [])]


def room_static(room: dict[str, Any], db: DbRoom) -> dict[str, Any]:
    """`--snapshot-log` 에 둘 방의 고정 정보. 단축어 프롬프트 원문·엔딩 이름·대화 프로필 전문은 시뮬레이터 로그에 두지
    않는다. 방 고정값(작품 버전·시작 설정·생성 모델·대화 프로필·`{{user}}` 이름)은 리플레이가 대조하고 프로필 전문으로
    지난 턴을 다시 조립한다. 생성 모델은 방 칸 값과 서버가 실제로 쓰는 값(허용을 거둔 상위 모델이면 기본 모델)을 둘 다
    남긴다."""
    snapshot = room.get("contentSnapshot") or {}
    return {
        "kind": "roomStatic",
        "roomId": room["id"],
        "at": _now(),
        "stats": _stat_defs(room),
        "endings": {e["id"]: e["name"] for e in snapshot.get("endings", [])},
        "shortcuts": [{"id": s["id"], "name": s["name"], "prompt": s["prompt"]} for s in snapshot.get("shortcuts", [])],
        **db.fixed.as_record(),
        "effectiveChatModel": room.get("effectiveChatModel"),
        "cellLabels": db.cell_labels,
    }


def _require_story(content_type: object) -> None:
    if content_type != "story":
        raise DriverExitError(2, f"스토리 작품만 다룬다(이 작품: {content_type}) — 캐릭터 방은 지원하지 않는다")


def check_same_database(room: dict[str, Any], db: DbRoom | None) -> DbRoom:
    """드라이버가 읽은 DB 가 `--base` 서버의 DB 인지 본다. 다르면 다른 DB 의 고정값을 이 방의 것으로 기록하게 된다.
    시작 설정 물리 행 id 가 가장 강한 증거다 — 물리 UUID 라 다른 DB 에서 우연히 맞을 수 없다."""
    if db is None:
        raise DriverExitError(2, f"방 {room['id']} 이 드라이버 DB 에 없다 — --base 서버와 다른 DB 를 읽고 있다")
    pinned = (room.get("contentSnapshot") or {}).get("pinnedStartingSetupId")
    server = (room.get("personaId"), room.get("turnCount"), pinned)
    mine = (_str_or_none(db.fixed.persona_id), db.turn_count, _str_or_none(db.fixed.pinned_starting_setup_id))
    if server != mine:
        raise DriverExitError(
            2, f"드라이버 DB 와 서버가 다르다(프로필 id·턴 수·시작 설정 행: 서버 {server} ≠ DB {mine})"
        )
    return db


def _str_or_none(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def room_after(room: dict[str, Any], static: dict[str, Any], source: str) -> dict[str, Any]:
    names = {s["id"]: s["name"] for s in static["stats"]}
    return {
        "turnCount": room.get("turnCount"),
        "stats": {names.get(k, k): v for k, v in (room.get("stats") or {}).items()},
        "endingReached": bool(room.get("endingReached")),
        "source": source,
    }


def stats_line(after: dict[str, Any], static: dict[str, Any]) -> str:
    units = {s["name"]: s["unit"] for s in static["stats"]}
    parts = [f"{name}={value:g}{units.get(name, '')}" for name, value in after["stats"].items()]
    ending = " ★엔딩도달" if after["endingReached"] else ""
    return f"[턴 {after['turnCount']}] " + "  ".join(parts) + ending


_BASELINE_KINDS = ("opening", "rebase", "check")


@dataclass
class LogState:
    """`--log` 에서 다시 읽는 누적 상태."""

    after: dict[str, Any] | None = None
    lost_turn: bool = False
    server_log_offset: int | None = None
    paused_at: set[int] = field(default_factory=set)
    last_memory: dict[str, Any] | None = None


def read_log_state(log: Path, room_id: str) -> LogState:
    state = LogState()
    for record in _records(log):
        if record.get("roomId") != room_id:
            continue
        kind = record.get("kind")
        if kind in _BASELINE_KINDS and record.get("roomAfter"):
            state.after = record["roomAfter"]
            state.lost_turn = False
        elif kind == "turn":
            if record.get("serverLogOffsetAfter") is not None:
                state.server_log_offset = record["serverLogOffsetAfter"]
            if record.get("memory") is not None:
                state.last_memory = record["memory"]
            if record.get("http") is None:
                # 연결 오류로 끝난 턴 — 서버가 마쳤는지 모르므로 유실로 본다.
                state.lost_turn = True
            elif record.get("http") == 200:
                if record.get("done"):
                    state.after = record["roomAfter"]
                    state.lost_turn = False
                else:
                    state.lost_turn = True
        elif kind == "pause":
            state.paused_at.add(int(record["turnCount"]))
        elif kind == "preCheck" and record.get("serverLogOffsetAfter") is not None:
            state.server_log_offset = record["serverLogOffsetAfter"]
    return state


def last_static(snapshot_log: Path, room_id: str) -> dict[str, Any] | None:
    found = None
    for record in _records(snapshot_log):
        if record.get("kind") == "roomStatic" and record.get("roomId") == room_id:
            found = record
    return found


def fetch_room(session: Session, room_id: str) -> dict[str, Any]:
    """방 조회. 메시지 꼬리 상한 파라미터를 함께 보낸다 — 그 파라미터가 없는 서버는 무시하고 전량을 준다."""
    return _ok(session.request("GET", f"/chat-rooms/{room_id}", params={"messageLimit": 1}), "방 조회")


# ── 서버 로그 · 정지 ─────────────────────────────────────────────────────────


def scan_gemini_429(server_log: Path, start: int | None, room_id: str) -> tuple[bool, int]:
    """`start` 이후 완결된 줄에서 이 방의 Gemini 429 흔적을 찾는다. 두 번째 값은 다음 검사 시작 위치(마지막 줄바꿈
    뒤) — 쓰는 중인 줄을 반으로 잘라 놓치지 않게 한다. 파일이 줄었으면(새로 만들어짐) 처음부터 본다."""
    if not server_log.exists():
        return False, 0
    size = server_log.stat().st_size
    if start is None:
        return False, size
    if size < start:
        start = 0
    with server_log.open("rb") as f:
        f.seek(start)
        chunk = f.read(size - start)
    end = chunk.rfind(b"\n")
    if end < 0:
        return False, start
    hit = False
    for line in chunk[: end + 1].decode("utf-8", errors="replace").splitlines():
        if room_id in line and not _ACCESS_LINE.search(line) and _GEMINI_429.search(line):
            hit = True
    return hit, start + end + 1


@dataclass(frozen=True)
class PauseRules:
    stop_file: Path | None
    pause_at: frozenset[int]


def _pause(log: Path, snapshot_log: Path, room_id: str, turn_count: int, trigger: str) -> DriverExitError:
    _append(log, {"kind": "pause", "roomId": room_id, "turnCount": turn_count, "at": _now()})
    _append(
        snapshot_log, {"kind": "pause", "roomId": room_id, "turnCount": turn_count, "trigger": trigger, "at": _now()}
    )
    return DriverExitError(10, PAUSE_NOTICE)


def check_pause_before_send(rules: PauseRules, state: LogState, log: Path, snapshot_log: Path, room_id: str) -> None:
    turn_count = int(state.after["turnCount"]) if state.after else 0
    if rules.stop_file is not None and rules.stop_file.exists():
        raise _pause(log, snapshot_log, room_id, turn_count, "stop-file")
    if turn_count in rules.pause_at and turn_count not in state.paused_at:
        raise _pause(log, snapshot_log, room_id, turn_count, "pause-at")


# ── 기억 (노트 쓰기 · 보내기 직전 스냅샷) ────────────────────────────────────


def read_note_file(raw: str) -> str:
    """서버는 앞뒤 공백을 뺀 뒤 길이를 본다. 넘으면 보내지 않는다."""
    text = Path(raw).read_text(encoding="utf-8").strip()
    if len(text) > MEMORY_NOTE_MAX_LENGTH:
        raise DriverExitError(9, f"노트가 {len(text)}자다 — {MEMORY_NOTE_MAX_LENGTH}자 이하로 줄여 다시 실행")
    return text


def put_note(session: Session, log: Path, room_id: str, note: str, turn_count: int) -> None:
    body = _ok(session.request("PUT", f"/chat-rooms/{room_id}/memory/note", json={"note": note}), "노트 저장")
    saved = body.get("note") or ""
    _append(
        log,
        {
            "kind": "noteUpdate",
            "roomId": room_id,
            "turnCount": turn_count,
            "at": _now(),
            "note": saved,
            "length": len(saved),
            "sha256": _sha(saved),
        },
    )


def memory_snapshot(
    session: Session, snapshot_log: Path, room_id: str, turn_count: int, previous: dict[str, Any] | None
) -> tuple[dict[str, Any], str]:
    """보내기 직전 기억. 턴 줄에는 해시·길이만, 바뀌었을 때만 전문을 `--snapshot-log` 에. 두 번째 값은 지금 노트 —
    시뮬레이터는 매 턴 출력에서 노트를 본다고 가정하므로 바뀌지 않은 턴에도 돌려준다."""
    body = _ok(session.request("GET", f"/chat-rooms/{room_id}/memory"), "기억 조회")
    note = body.get("note") or ""
    summary = body.get("summary") or {}
    summary_text = summary.get("text") or ""
    memory = {
        "noteSha": _sha(note),
        "noteLen": len(note),
        "summarySha": _sha(summary_text),
        "summaryLen": len(summary_text),
        "summarySource": summary.get("source"),
        "summaryUpdatedAt": summary.get("updatedAt"),
    }
    if (
        previous is None
        or previous.get("noteSha") != memory["noteSha"]
        or previous.get("summarySha") != memory["summarySha"]
    ):
        _append(
            snapshot_log,
            {
                "kind": "memorySnapshot",
                "roomId": room_id,
                "turnBefore": turn_count,
                # 이 스냅숏 바로 뒤에 보내는 턴이 성공하면 갖게 될 방 턴 수.
                "turn": turn_count + 1,
                "at": _now(),
                "note": note,
                "summary": summary_text,
                **memory,
            },
        )
    return memory, note


# ── 턴 전송 ─────────────────────────────────────────────────────────────────


@dataclass
class TurnResult:
    status: int
    reply: str = ""
    events: list[tuple[str, Any, Any]] = field(default_factory=list)
    done: bool = False
    image_id: str | None = None
    message_id: str | None = None
    failure: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    ttft_ms: int | None = None


def _iter_events(response: httpx.Response) -> Iterator[dict[str, Any]]:
    for line in response.iter_lines():
        if line.startswith("data: "):
            event: dict[str, Any] = json.loads(line[6:])
            yield event


def send_turn(session: Session, room_id: str, body: dict[str, Any]) -> TurnResult:
    """한 턴을 보내고 SSE 를 끝까지 읽는다. 401 은 다시 로그인해 한 번만 다시 보낸다."""
    for attempt in (0, 1):
        started = time.monotonic()
        with session.client.stream("POST", f"/chat-rooms/{room_id}/messages", json=body) as response:
            if response.status_code == 401 and attempt == 0:
                response.read()
                relogin = True
            else:
                relogin = False
                result = TurnResult(status=response.status_code)
                if response.status_code != 200:
                    response.read()
                    result.failure = f"HTTP {response.status_code}: {response.text[:300]}"
                    result.detail = _detail(response)
                    return result
                for event in _iter_events(response):
                    kind = event.get("type")
                    if kind == "token":
                        if result.ttft_ms is None:
                            result.ttft_ms = round((time.monotonic() - started) * 1000)
                        result.reply += event.get("delta", "")
                    elif kind == "statChange":
                        result.events.append(("stat", event.get("statId"), event.get("newValue")))
                    elif kind == "endingReached":
                        result.events.append(("ENDING", event.get("endingId"), event.get("epilogue")))
                    elif kind in ("error", "policyWarning"):
                        result.events.append((kind, event.get("message"), None))
                        result.failure = result.failure or f"{kind}: {event.get('message')}"
                    elif kind == "done":
                        result.done = True
                        final = event.get("finalMessage") or {}
                        result.image_id = final.get("imageId")
                        result.message_id = final.get("id")
                        if not result.reply:
                            result.reply = final.get("content") or ""
                return result
        if relogin:
            session.relogin()
    raise DriverExitError(2, "HTTP 401: 다시 로그인한 뒤에도 거부")


# ── 모드 ────────────────────────────────────────────────────────────────────


def create_room(
    args: argparse.Namespace, session: Session, read_db: DbRoomReader, log: Path, snapshot_log: Path
) -> int:
    detail = _ok(session.request("GET", f"/contents/{args.content_id}"), "작품 조회")
    _require_story(detail.get("type"))
    setup = (detail.get("startingSetups") or [])[args.setup]
    created = session.request(
        "POST",
        "/chat-rooms",
        json={"contentId": args.content_id, "contentType": "story", "startingSetupId": setup["id"]},
    )
    room = _ok(created, "방 만들기")
    room_id = room["id"]
    db = check_same_database(room, read_db(room_id))
    static = room_static(room, db)
    labels = db.cell_labels
    user_name = db.fixed.user_name
    _append(snapshot_log, static)
    guide = _ok(session.request("GET", f"/chat-rooms/{room_id}/play-guide"), "플레이가이드").get("playGuide")
    messages = [render_author_text(m["content"], user_name, labels) for m in room.get("messages") or []]
    chips = [
        render_author_text(c, user_name, labels)
        for c in (room.get("contentSnapshot") or {}).get("suggestedReplies") or []
    ]
    guide_text = render_author_text(guide, user_name, labels) if guide else None
    after = room_after(room, static, "create")
    pinned = (room.get("contentSnapshot") or {}).get("pinnedStartingSetupId")
    print(f"room={room_id}  「{detail.get('name')}」 / 시작설정: {setup['name']}")
    print(f"contentVersionId={db.fixed.content_version_id}  effectiveChatModel={room.get('effectiveChatModel')}")
    print(f"startingSetupId={room.get('startingSetupId')}  pinnedStartingSetupId={pinned}")
    for message in messages:
        print(f"\n{message}")
    print("\n추천 답변:")
    for chip in chips:
        print(f"  - {chip}")
    print(f"\n플레이 가이드:\n{guide_text or '(없음)'}")
    print("\n단축어: " + ", ".join(s["name"] for s in static["shortcuts"]))
    print("\n" + stats_line(after, static))
    _append(
        log,
        {
            "kind": "meta",
            "roomId": room_id,
            "contentId": args.content_id,
            "storyName": detail.get("name"),
            "setupIndex": args.setup,
            "setupName": setup["name"],
            "startingSetupId": room.get("startingSetupId"),
            "pinnedStartingSetupId": pinned,
            "shortcutNames": [s["name"] for s in static["shortcuts"]],
            "base": args.base,
            "createdAt": _now(),
        },
    )
    _append(
        log,
        {
            "kind": "opening",
            "roomId": room_id,
            "messages": messages,
            "suggestedReplies": chips,
            "playGuide": guide_text,
            "roomAfter": after,
        },
    )
    return 0


def rebase(
    session: Session, read_db: DbRoomReader, log: Path, snapshot_log: Path, room_id: str, reason: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """전체 조회로 누적 기준을 다시 잡는다. 방 고정값도 다시 읽어 남긴다 — 사람 구간에 화면에서 프로필이나 모델을
    바꿨다면 그 뒤 턴의 리플레이 대조가 이 기록을 본다."""
    room = fetch_room(session, room_id)
    _require_story(room.get("contentType"))
    db = check_same_database(room, read_db(room_id))
    static = room_static(room, db)
    _append(snapshot_log, static)
    after = room_after(room, static, "refetch")
    _append(log, {"kind": "rebase", "roomId": room_id, "at": _now(), "reason": reason, "roomAfter": after})
    return after, static


def pause_rules(args: argparse.Namespace) -> PauseRules:
    return PauseRules(
        stop_file=Path(args.stop_file) if args.stop_file else None,
        pause_at=frozenset(int(x) for x in args.pause_at.split(",") if x.strip()) if args.pause_at else frozenset(),
    )


def play_turn(
    args: argparse.Namespace,
    session_factory: Callable[[], Session],
    read_db: DbRoomReader,
    log: Path,
    snapshot_log: Path,
) -> int:
    room_id: str = args.room
    rules = pause_rules(args)
    note = read_note_file(args.set_note) if args.set_note else None
    state = read_log_state(log, room_id)
    # 네트워크 전에 정지부터 본다 — 멈출 차례면 로그인도 하지 않는다.
    check_pause_before_send(rules, state, log, snapshot_log, room_id)

    static = last_static(snapshot_log, room_id)
    if static is not None and RoomFixed.from_record(static) is None:
        # 방 고정값을 기록하기 전의 옛 로그다. 이어 치면 이름 치환에 쓸 `{{user}}` 이름도, 리플레이가 대조할 값도 없다.
        raise DriverExitError(2, "이 방의 고정값 기록이 없다 — --rebase 를 먼저 실행해 다시 기록한 뒤 이어 친다")

    session: Session = session_factory()
    if state.after is None or state.lost_turn or static is None:
        reason = "유실 턴 뒤" if state.lost_turn else "기준 없음"
        state.after, static = rebase(session, read_db, log, snapshot_log, room_id, reason)
        state.lost_turn = False
    assert state.after is not None
    labels: dict[str, str] = static.get("cellLabels") or {}
    turn_before = int(state.after["turnCount"])

    retry_at = log.parent / ".retry_at"
    stamp = log.parent / ".last_turn"
    wake = float(stamp.read_text()) + MIN_GAP if stamp.exists() else 0.0
    if retry_at.exists():
        wake = max(wake, float(retry_at.read_text()))
    if wake > time.time():
        time.sleep(wake - time.time())
    stamp.write_text(str(time.time()))
    # 기다리는 사이 정지 파일이 생겼을 수 있다.
    check_pause_before_send(rules, state, log, snapshot_log, room_id)

    server_log = Path(args.server_log) if args.server_log else None
    offset: int | None = None
    # 직전 턴 뒤 백그라운드 요약 접기의 429 는 그 턴의 사후 검사 뒤에 찍힐 수 있다 — 보내기 전에 한 번 더 본다.
    hit = False
    if server_log is not None:
        hit, offset = scan_gemini_429(server_log, state.server_log_offset, room_id)
    if hit:
        _append(
            log,
            {
                "kind": "preCheck",
                "roomId": room_id,
                "at": _now(),
                "geminiRateLimited": True,
                "serverLogOffsetAfter": offset,
            },
        )
        raise DriverExitError(5, RATE_LIMIT_NOTICE)

    if note is not None:
        put_note(session, log, room_id, note, turn_before)
    memory, current_note = memory_snapshot(session, snapshot_log, room_id, turn_before, state.last_memory)
    print(f"[기억 노트]\n{current_note or '(비어 있음)'}\n")

    user_name: str = static["userName"]
    shortcut = None
    if args.shortcut is not None:
        shortcut = next((s for s in static["shortcuts"] if s["name"] == args.shortcut), None)
        if shortcut is None:
            raise DriverExitError(
                1, f"단축어가 없다: {args.shortcut} (있는 것: {', '.join(s['name'] for s in static['shortcuts'])})"
            )
        content = expand_author_macros(shortcut["prompt"], user_name=user_name, char_name=None)
        body: dict[str, Any] = {"content": content, "shortcutId": shortcut["id"]}
    else:
        content = expand_author_macros(args.say, user_name=user_name, char_name=None)
        body = {"content": content}

    record: dict[str, Any] = {
        "kind": "turn",
        "roomId": room_id,
        # 서버 턴 수 + 1 — 프롬프트 덤프의 `turn` 과 같은 번호다. 성공한 드라이버 턴 수로 세면 유실 턴(200 인데
        # 완료 없음)과 사람 턴 뒤에 덤프 번호와 어긋난다.
        "clientTurn": turn_before + 1,
        "turnBefore": turn_before,
        "sentAt": _now(),
        "tag": args.tag,
        # 단축어 턴은 비운다 — 시뮬레이터가 읽는 파일에 단축어 원문을 두지 않는다. 리플레이는 DB 메시지로 재현한다.
        "userText": None if shortcut is not None else content,
        "shortcut": shortcut["name"] if shortcut is not None else None,
        "shortcutId": shortcut["id"] if shortcut is not None else None,
        "memory": memory,
    }
    started = time.monotonic()
    try:
        result = send_turn(session, room_id, body)
    except httpx.TransportError as lost:
        # 스트림 도중 연결이 끊기거나 시간이 다 됐다. 서버는 그 턴을 마쳤을 수도 있으므로 줄을 남겨 다음 실행이 유실
        # 턴으로 보고 조회로 기준을 다시 잡게 한다 — 줄 없이 끝나면 직전 기준을 믿어 턴 수·스탯이 밀린 채 기록된다.
        record.update(
            seconds=round(time.monotonic() - started, 1),
            http=None,
            done=False,
            reply="",
            failure=f"transport: {type(lost).__name__}: {lost}",
            roomAfter=None,
        )
        _append(log, record)
        raise DriverExitError(1, f"연결 오류 — {record['failure']}") from None
    record["seconds"] = round(time.monotonic() - started, 1)
    record["ttftMs"] = result.ttft_ms
    record["http"] = result.status
    record["done"] = result.done
    # 사전 검사가 끝난 줄 경계부터 이어 본다 — 노트 저장·기억 조회 사이에 찍힌 줄(직전 턴 요약 접기의 실패)도
    # 여기서 걸린다. 보내기 직전 파일 크기부터 보면 그 구간을 아무도 보지 않고, 크기가 줄 중간이면 앞 조각도 잘린다.
    rate_limited = False
    if server_log is not None:
        rate_limited, offset_after = scan_gemini_429(server_log, offset, room_id)
        record["serverLogOffsetAfter"] = offset_after
        if rate_limited:
            record["geminiRateLimited"] = True

    if result.status != 200:
        code = result.detail.get("code")
        record.update(reply="", statChanges=[], ending=None, failure=result.failure, roomAfter=None, appCode=code)
        if result.status == 429:
            record["retryAfterSeconds"] = result.detail.get("retryAfterSeconds")
        _append(log, record)
        print(result.failure)
        if rate_limited:
            raise DriverExitError(5, RATE_LIMIT_NOTICE)
        if result.status == 429 and code in CLOVER_CODES:
            raise DriverExitError(7, f"클로버 429 {code} — 계정·격리 설정 확인, 실행한 쪽에 보고")
        if result.status == 429:
            retry_after = result.detail.get("retryAfterSeconds")
            if isinstance(retry_after, (int, float)):
                retry_at.write_text(str(time.time() + retry_after))
            raise DriverExitError(4, f"retryAfterSeconds={retry_after}")
        if result.status == 409 and code == TURN_IN_PROGRESS_CODE:
            raise DriverExitError(6, "턴 진행 중(409) — 메시지는 저장되지 않았다")
        if result.status == 403:
            raise DriverExitError(2, result.failure or "HTTP 403")
        raise DriverExitError(1, result.failure or f"HTTP {result.status}")

    if shortcut is not None:
        print(f"[단축어: {shortcut['name']}]\n")
    print(result.reply)
    stat_names = {s["id"]: s["name"] for s in static["stats"]}
    after = {**state.after, "stats": dict(state.after["stats"]), "source": "sse"}
    stat_changes = []
    ending = None
    for kind, a, b in result.events:
        if kind == "stat":
            name = stat_names.get(a, a)
            after["stats"][name] = b
            stat_changes.append({"name": name, "value": b})
            print(f"\n  · {name} → {b:g}")
        elif kind == "ENDING":
            epilogue = render_author_text(b, user_name, labels) if b else b
            ending = {"id": a, "name": static["endings"].get(a, a), "epilogue": epilogue}
            after["endingReached"] = True
            print(f"\n  ★★ 엔딩 도달: 「{ending['name']}」\n  에필로그: {epilogue}")
        else:
            print(f"\n  !! {kind}: {a}")
    label = cell_label(result.image_id, labels)
    if label is not None:
        print(f"\n[그림: {label}]")
    if result.done:
        after["turnCount"] = turn_before + 1
        print("\n" + stats_line(after, static))
    record.update(
        # 완료 없이 끝난 턴의 조각은 `reply` 에 두지 않는다 — 재시도 줄과 턴 번호가 같아, 쌍 판정 도구가 같은 턴에
        # 응답을 둘로 읽는다. 조각은 `partialReply` 에만 남긴다.
        reply=result.reply if result.done else "",
        partialReply=None if result.done else result.reply,
        statChanges=stat_changes,
        imageId=result.image_id,
        imageLabel=label,
        # 리플레이가 DB 메시지에서 이 턴의 (사용자, 응답) 쌍을 찾았는지 대조하는 데 쓴다.
        assistantMessageId=result.message_id,
        ending=ending,
        failure=result.failure,
        roomAfter=after if result.done else None,
    )
    _append(log, record)
    if rate_limited:
        raise DriverExitError(5, RATE_LIMIT_NOTICE)
    if not result.done:
        return 0

    if args.check_every > 0 and after["turnCount"] % args.check_every == 0:
        room = fetch_room(session, room_id)
        fetched = room_after(room, static, "refetch")
        mismatch = (
            fetched["turnCount"] != after["turnCount"]
            or fetched["endingReached"] != after["endingReached"]
            or {k: float(v) for k, v in fetched["stats"].items()} != {k: float(v) for k, v in after["stats"].items()}
        )
        _append(
            log,
            {
                "kind": "check",
                "roomId": room_id,
                "at": _now(),
                "ok": not mismatch,
                "accumulated": after,
                "roomAfter": None if mismatch else fetched,
                "fetched": fetched,
            },
        )
        if mismatch:
            raise DriverExitError(8, "누적값과 조회값이 다르다 — 실행한 쪽에 보고")
    if ending is not None:
        return 3
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="API 서버 base URL (필수 — 빠뜨리면 공유 dev 서버로 간다)")
    ap.add_argument("--cred-file", required=True, help="저장소 밖 0600 JSON {email, password}")
    ap.add_argument("--cookie-file", required=True, help="저장소 밖 0600 세션 쿠키 값 파일(없으면 로그인해 만든다)")
    ap.add_argument("--log", required=True, help="시뮬레이터 JSONL. 간격 스탬프도 이 옆에 둔다")
    ap.add_argument(
        "--snapshot-log", required=True, help="시뮬레이터가 읽지 않는 JSONL(기억 전문·정지 이유·방 정적 정보)"
    )
    ap.add_argument("--content-id", help="방 만들기: 작품 id")
    ap.add_argument("--setup", type=int, default=0, help="방 만들기: 시작설정 인덱스")
    ap.add_argument("--room")
    ap.add_argument("--say")
    ap.add_argument("--shortcut", help="단축어 이름 — 화면 버튼과 같이 프롬프트 원문과 단축어 id 를 보낸다")
    ap.add_argument("--tag", help="턴에 붙일 꼬리표(자유 문자열) — 로그에만 남긴다")
    ap.add_argument("--set-note", help="보내기 전에 기억 노트를 이 파일 내용으로 덮어쓴다")
    ap.add_argument("--server-log", help="서버 로그 — 주면 이 방의 Gemini 429 흔적을 보고 종료 코드 5")
    ap.add_argument(
        "--check-every", type=int, default=25, help="방 턴 수가 이 배수일 때 조회로 누적값을 대조한다(0 이면 안 함)"
    )
    ap.add_argument("--stop-file", help="보내기 전에 이 파일이 있으면 보내지 않고 종료 코드 10")
    ap.add_argument("--pause-at", help="방 턴 수 목록(쉼표) — 그 턴 수에서 다음 턴을 보내기 전에 한 번 종료 코드 10")
    ap.add_argument("--rebase", metavar="REASON", help="전체 조회로 누적 기준을 다시 잡는다(사유 기록)")
    ap.add_argument("--state", action="store_true", help="전체 조회로 상태만 출력(기록 안 함)")
    return ap


def main(
    argv: list[str] | None = None,
    transport: httpx.BaseTransport | None = None,
    room_fixed_reader: DbRoomReader | None = None,
) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    turn = args.say is not None or args.shortcut is not None
    if args.say is not None and args.shortcut is not None:
        ap.error("--say 와 --shortcut 은 함께 쓸 수 없다")
    if turn and not args.room:
        ap.error("턴에는 --room 이 필요하다")
    log = Path(args.log)
    snapshot_log = Path(args.snapshot_log)
    if log.resolve() == snapshot_log.resolve():
        ap.error("--snapshot-log 는 --log 와 다른 파일이어야 한다")

    def session_factory() -> Session:
        return Session(args.base, args.cred_file, args.cookie_file, log, transport)

    def db_reader() -> DbRoomReader:
        return room_fixed_reader if room_fixed_reader is not None else default_db_reader()

    try:
        if args.content_id:
            # DB 읽기 함수를 먼저 만든다 — 기본 읽기는 만들 때 운영 DB 를 거부하므로 로그인보다 앞서야 한다.
            read_db = db_reader()
            return create_room(args, session_factory(), read_db, log, snapshot_log)
        if not args.room:
            ap.error("--content-id 또는 --room 이 필요하다")
        if args.state:
            room = fetch_room(session_factory(), args.room)
            static = {"stats": _stat_defs(room)}
            print(stats_line(room_after(room, static, "refetch"), static))
            return 0
        if args.rebase:
            read_db = db_reader()
            after, static = rebase(session_factory(), read_db, log, snapshot_log, args.room, args.rebase)
            print(stats_line(after, static))
            return 0
        if turn:
            return play_turn(args, session_factory, db_reader(), log, snapshot_log)
        if args.set_note:
            note = read_note_file(args.set_note)
            state = read_log_state(log, args.room)
            put_note(session_factory(), log, args.room, note, int(state.after["turnCount"]) if state.after else 0)
            return 0
        ap.error("할 일이 없다 — --say·--shortcut·--set-note·--rebase·--state 중 하나")
    except DriverExitError as stop:
        print(stop.message)
        return stop.code
    return 0


if __name__ == "__main__":
    sys.exit(main())
