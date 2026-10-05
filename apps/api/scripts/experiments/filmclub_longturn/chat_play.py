"""장기 턴 측정용 한 턴 드라이버. 시뮬레이터(대화 에이전트)가 응답을 읽고 다음 말을 정해 한 번에 한 턴씩 부른다.
chat-tuning 실험의 `scripts/chat_play.py` 를 출발점으로, 복제 작품·수백 턴·기억 노트·정지 지점에 맞게 고쳤다.

    # 방 만들기(오케스트레이터만): 오프닝·추천 답변·플레이가이드를 출력하고 버전 번호·시작설정 id 를 남긴다
    python chat_play.py --base <url> --cred-file <f> --cookie-file <f> --log <run>/x.jsonl \\
        --snapshot-log <run>/memory-snapshots.jsonl --replica <run>/replica --content-id <uuid> --setup 0
    # 한 턴(--say 또는 --shortcut 중 하나)
    python chat_play.py ... --room <id> --server-log <run>/server.log --say "안녕하세요" [--tag 넘김] \\
        [--set-note <노트 파일>] [--stop-file <f>] [--pause-at 100,250]
    python chat_play.py ... --room <id> --rebase "사람 구간 끝"   # 전체 조회로 누적값을 다시 잡는다
    python chat_play.py ... --room <id> --state                   # 상태만 출력(기록 안 함)

`--base` 는 필수다 — 기본값을 두면 빠뜨렸을 때 공유 dev 서버에 방이 생긴다.

로그인: 로그인 요청은 성공·실패 무관하게 이메일당 15분 상한에 세지고 면제 계정도 예외가 아니다. 그래서 실행마다
로그인하지 않고 세션 쿠키 **값**만 저장소 밖 0600 파일에 두고 다시 쓴다. 도메인 없이 넣어야 `--base` 의 호스트 표기가
바뀌어도 실린다. 401 이면 한 번 다시 로그인하고 같은 요청을 다시 보낸다(401 은 사용자 메시지 커밋 전에 난다). 상한 창
안에서 두 번째 로그인이 필요해지면 조용한 재로그인 반복이 상한을 다 쓰기 전에 멈춘다.

누적 상태: 턴마다 방 전체를 다시 받으면 메시지가 수백 개인 방에서 턴마다 수 MB 가 오간다. 스탯은 SSE `statChange`
의 새 값으로 덮어쓰고, 턴 수는 `done` 마다 +1, 엔딩은 `endingReached` 로 안다. 이 누적값은 프로세스마다 새로 뜨므로
`--log` 의 마지막 기준(오프닝·턴·재기준·대조 줄의 `roomAfter`)에서 읽는다. 25턴마다 한 번 방을 조회해 대조하고 어긋나면
멈춘다. 유실 턴(생성 오류) 뒤에는 다음 실행이 먼저 조회로 기준을 다시 잡는다. 사람 턴·서버 재기동 뒤에는
오케스트레이터가 `--rebase` 로 다시 잡는다.

은폐: `--log` 는 시뮬레이터가 읽을 수 있다. 화면에 보이는 것만 남긴다 — 스탯 설명, 엔딩 판정문·규칙, 도달 전
에필로그, 단축어 프롬프트 원문, 대화 요약 본문, 정지 이유는 넣지 않는다. 그런 것은 `--snapshot-log`(시뮬레이터 읽기
금지 파일)에 둔다. 출력도 같다 — 기억은 노트만 보여 준다.

종료 코드: 0 정상(생성 오류·정책 경고로 유실된 턴 포함 — 출력에 이유가 나간다) · 1 그 밖의 HTTP 오류 · 2 인증(401
재로그인 실패·403·자격 파일 거부·로그인 429·상한 창 안 두 번째 로그인, 인자 오류도 argparse 가 2) · 3 엔딩 도달 ·
4 앱 버스트 429(같은 명령을 다시 실행하면 retryAfterSeconds 만큼 기다린다) · 5 Gemini 한도(서버 로그에 이 방의 429) ·
6 턴 진행 중 409 · 7 클로버 429 · 8 누적값과 조회값 불일치 · 9 노트가 길이 상한을 넘음 · 10 일시 정지(정지 파일 ·
`--pause-at` · 정해 둔 스탯 값 첫 도달).
"""

import argparse
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

from api.chat.schemas import MEMORY_NOTE_MAX_LENGTH
from api.chat.turn_lock import TURN_IN_PROGRESS_CODE
from api.content.author_macros import expand_author_macros, resolve_user_name
from api.content.media_tags import media_tag_refs
from api.core.config import settings
from api.core.rate_limit import LOGIN_EMAIL_WINDOW_SECONDS

MIN_GAP = 10.0
CHECK_EVERY = 25
CLOVER_CODES = frozenset({"CLOVER_REQUIRED", "CLOVER_CONFIRM_REQUIRED"})
RATE_LIMIT_NOTICE = "측정 중단: 외부 한도 — 오케스트레이터에게 보고"
PAUSE_NOTICE = "일시 정지 — 오케스트레이터에게 보고"
# 서버 로그에서 Gemini 429 흔적. 예외 클래스 이름·Sentry 태그는 로그에 찍히지 않고, 생성·판정·요약 실패 줄이 예외
# 문자열(genai `APIError` 의 `"429 RESOURCE_EXHAUSTED. …"`)과 방 id 를 함께 싣는다. 숫자 429 만으로는 보지 않는다 —
# 모든 줄 앞 시각의 밀리초(`…:43.429+0900`)와 사용량 줄의 토큰 수(`candidates_tokens=429`)가 같은 숫자가 된다.
# 접근 로그 줄은 앱이 낸 429(버스트·클로버)라 뺀다.
_GEMINI_429 = re.compile(r"RESOURCE_EXHAUSTED")
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


# ── 화면 글 (작가 글 이름 치환 · 그림 태그) ──────────────────────────────────


def load_cell_labels(replica: Path) -> dict[uuid.UUID, str]:
    """칸 entity_id → "인물/장면". API 는 칸 이름을 주지 않고 화면 글의 태그는 칸 id 형태라, 복제본 행에서 찾는다.
    발행 복제는 entity_id 를 보존하므로 복제본(v5) 행이 측정 버전의 칸에도 맞는다."""

    def rows(name: str) -> list[dict[str, Any]]:
        data: list[dict[str, Any]] = json.loads((replica / f"{name}.json").read_text(encoding="utf-8"))
        return data

    people = {r["entity_id"]: r["name"] for r in rows("media_book_people")}
    scenes = {r["entity_id"]: r["name"] for r in rows("media_book_scenes")}
    return {
        uuid.UUID(c["entity_id"]): f"{people.get(c['person_entity_id'], '?')}/{scenes.get(c['scene_entity_id'], '?')}"
        for c in rows("media_book_cells")
    }


@dataclass(frozen=True)
class Names:
    persona_name: str | None
    default_user_name: str
    char_name: str | None

    @classmethod
    def from_room(cls, room: dict[str, Any]) -> "Names":
        char_name = room.get("contentName") if room.get("contentType") == "character" else None
        return cls(room.get("personaName"), room.get("defaultUserName") or "", char_name)

    def as_record(self) -> dict[str, Any]:
        return {"personaName": self.persona_name, "defaultUserName": self.default_user_name, "charName": self.char_name}


def render_author_text(text: str, names: Names, labels: dict[uuid.UUID, str]) -> str:
    """작가 글(오프닝·추천 답변·플레이가이드·에필로그)을 화면과 같게 바꾼다. 칸 태그는 그림 대신 `[그림: 인물/장면]` —
    복제본에 없는 칸은 화면처럼 지운다. 태그를 먼저 바꾸고 이름을 바꾼다(서버 빌더와 같은 순서). 모델 응답은 화면이
    바꾸지 않으므로 이 함수를 지나지 않는다."""
    for cell_id in media_tag_refs(text):
        label = labels.get(cell_id)
        text = text.replace("{{img::" + str(cell_id) + "}}", f"[그림: {label}]" if label else "")
    user_name = resolve_user_name(names.persona_name, names.default_user_name)
    return expand_author_macros(text, user_name=user_name, char_name=names.char_name)


def cell_label(image_id: str | None, labels: dict[uuid.UUID, str]) -> str | None:
    if not image_id:
        return None
    try:
        return labels.get(uuid.UUID(image_id), "(복제본에 없는 칸)")
    except ValueError:
        return "(복제본에 없는 칸)"


# ── 방 정적 정보 · 누적 상태 ─────────────────────────────────────────────────


def room_static(room: dict[str, Any]) -> dict[str, Any]:
    """`--snapshot-log` 에 둘 방의 고정 정보. 단축어 프롬프트 원문·엔딩 이름은 시뮬레이터 로그에 두지 않는다."""
    snapshot = room.get("contentSnapshot") or {}
    return {
        "kind": "roomStatic",
        "roomId": room["id"],
        "at": _now(),
        "stats": [{"id": s["id"], "name": s["name"], "unit": s.get("unit") or ""} for s in snapshot.get("stats", [])],
        "endings": {e["id"]: e["name"] for e in snapshot.get("endings", [])},
        "shortcuts": [{"id": s["id"], "name": s["name"], "prompt": s["prompt"]} for s in snapshot.get("shortcuts", [])],
        "names": Names.from_room(room).as_record(),
    }


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
    succeeded_turns: int = 0


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
            if record.get("http") == 200:
                state.succeeded_turns += 1
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
    milestone_stat: str
    milestones: tuple[float, ...]


def _pause(log: Path, snapshot_log: Path, room_id: str, turn_count: int, trigger: str, **extra: Any) -> DriverExitError:
    _append(log, {"kind": "pause", "roomId": room_id, "turnCount": turn_count, "at": _now()})
    _append(
        snapshot_log,
        {"kind": "pause", "roomId": room_id, "turnCount": turn_count, "trigger": trigger, "at": _now(), **extra},
    )
    return DriverExitError(10, PAUSE_NOTICE)


def check_pause_before_send(rules: PauseRules, state: LogState, log: Path, snapshot_log: Path, room_id: str) -> None:
    turn_count = int(state.after["turnCount"]) if state.after else 0
    if rules.stop_file is not None and rules.stop_file.exists():
        raise _pause(log, snapshot_log, room_id, turn_count, "stop-file")
    if turn_count in rules.pause_at and turn_count not in state.paused_at:
        raise _pause(log, snapshot_log, room_id, turn_count, "pause-at")


def reached_milestones(snapshot_log: Path, room_id: str) -> set[float]:
    return {
        float(r["threshold"])
        for r in _records(snapshot_log)
        if r.get("roomId") == room_id and r.get("kind") in ("pause", "milestone") and r.get("threshold") is not None
    }


def new_milestones(rules: PauseRules, after: dict[str, Any], already: set[float]) -> list[float]:
    value = after["stats"].get(rules.milestone_stat)
    if value is None:
        return []
    return [t for t in rules.milestones if value <= t and t not in already]


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
                        if not result.reply:
                            result.reply = final.get("content") or ""
                return result
        if relogin:
            session.relogin()
    raise DriverExitError(2, "HTTP 401: 다시 로그인한 뒤에도 거부")


# ── 모드 ────────────────────────────────────────────────────────────────────


def create_room(args: argparse.Namespace, session: Session, log: Path, snapshot_log: Path) -> int:
    labels = load_cell_labels(Path(args.replica))
    detail = _ok(session.request("GET", f"/contents/{args.content_id}"), "작품 조회")
    setup = (detail.get("startingSetups") or [])[args.setup]
    created = session.request(
        "POST",
        "/chat-rooms",
        json={"contentId": args.content_id, "contentType": "story", "startingSetupId": setup["id"]},
    )
    room = _ok(created, "방 만들기")
    room_id = room["id"]
    static = room_static(room)
    _append(snapshot_log, static)
    names = Names.from_room(room)
    guide = _ok(session.request("GET", f"/chat-rooms/{room_id}/play-guide"), "플레이가이드").get("playGuide")
    messages = [render_author_text(m["content"], names, labels) for m in room.get("messages") or []]
    chips = [
        render_author_text(c, names, labels) for c in (room.get("contentSnapshot") or {}).get("suggestedReplies") or []
    ]
    guide_text = render_author_text(guide, names, labels) if guide else None
    after = room_after(room, static, "create")
    pinned = (room.get("contentSnapshot") or {}).get("pinnedStartingSetupId")
    print(f"room={room_id}  「{detail.get('name')}」 v{detail.get('versionNumber')} / 시작설정: {setup['name']}")
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
            "versionNumber": detail.get("versionNumber"),
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
    session: Session, log: Path, snapshot_log: Path, room_id: str, reason: str, rules: PauseRules | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """전체 조회로 누적 기준을 다시 잡는다. 이미 넘은 정지 기준 값은 도달로 적어 다음 턴이 뒤늦게 멈추지 않게 한다."""
    room = fetch_room(session, room_id)
    static = room_static(room)
    _append(snapshot_log, static)
    after = room_after(room, static, "refetch")
    _append(log, {"kind": "rebase", "roomId": room_id, "at": _now(), "reason": reason, "roomAfter": after})
    if rules is not None:
        for threshold in new_milestones(rules, after, reached_milestones(snapshot_log, room_id)):
            _append(
                snapshot_log,
                {
                    "kind": "milestone",
                    "roomId": room_id,
                    "turnCount": after["turnCount"],
                    "threshold": threshold,
                    "at": _now(),
                },
            )
    return after, static


def pause_rules(args: argparse.Namespace) -> PauseRules:
    return PauseRules(
        stop_file=Path(args.stop_file) if args.stop_file else None,
        pause_at=frozenset(int(x) for x in args.pause_at.split(",") if x.strip()) if args.pause_at else frozenset(),
        milestone_stat=args.milestone_stat,
        milestones=tuple(sorted((float(x) for x in args.milestones.split(",") if x.strip()), reverse=True)),
    )


def play_turn(args: argparse.Namespace, session_factory: Callable[[], Session], log: Path, snapshot_log: Path) -> int:
    room_id: str = args.room
    labels = load_cell_labels(Path(args.replica))
    rules = pause_rules(args)
    note = read_note_file(args.set_note) if args.set_note else None
    state = read_log_state(log, room_id)
    # 네트워크 전에 정지부터 본다 — 멈출 차례면 로그인도 하지 않는다.
    check_pause_before_send(rules, state, log, snapshot_log, room_id)

    session: Session = session_factory()
    static = last_static(snapshot_log, room_id)
    if state.after is None or state.lost_turn or static is None:
        reason = "유실 턴 뒤" if state.lost_turn else "기준 없음"
        state.after, static = rebase(session, log, snapshot_log, room_id, reason, rules)
        state.lost_turn = False
    assert state.after is not None
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

    server_log = Path(args.server_log)
    # 직전 턴 뒤 백그라운드 요약 접기의 429 는 그 턴의 사후 검사 뒤에 찍힐 수 있다 — 보내기 전에 한 번 더 본다.
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

    names = Names(static["names"]["personaName"], static["names"]["defaultUserName"], static["names"]["charName"])
    user_name = resolve_user_name(names.persona_name, names.default_user_name)
    shortcut = None
    if args.shortcut is not None:
        shortcut = next((s for s in static["shortcuts"] if s["name"] == args.shortcut), None)
        if shortcut is None:
            raise DriverExitError(
                1, f"단축어가 없다: {args.shortcut} (있는 것: {', '.join(s['name'] for s in static['shortcuts'])})"
            )
        content = expand_author_macros(shortcut["prompt"], user_name=user_name, char_name=names.char_name)
        body: dict[str, Any] = {"content": content, "shortcutId": shortcut["id"]}
    else:
        content = expand_author_macros(args.say, user_name=user_name, char_name=names.char_name)
        body = {"content": content}

    record: dict[str, Any] = {
        "kind": "turn",
        "roomId": room_id,
        "clientTurn": state.succeeded_turns + 1,
        "turnBefore": turn_before,
        "sentAt": _now(),
        "tag": args.tag,
        "userText": None if shortcut is not None else content,
        "shortcut": shortcut["name"] if shortcut is not None else None,
        "memory": memory,
    }
    started = time.monotonic()
    pre_size = server_log.stat().st_size if server_log.exists() else 0
    result = send_turn(session, room_id, body)
    record["seconds"] = round(time.monotonic() - started, 1)
    record["ttftMs"] = result.ttft_ms
    record["http"] = result.status
    record["done"] = result.done
    rate_limited, offset_after = scan_gemini_429(server_log, pre_size, room_id)
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
            raise DriverExitError(7, f"클로버 429 {code} — 계정·격리 설정 확인, 오케스트레이터에게 보고")
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
            epilogue = render_author_text(b, names, labels) if b else b
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
        reply=result.reply,
        statChanges=stat_changes,
        imageId=result.image_id,
        imageLabel=label,
        ending=ending,
        failure=result.failure,
        roomAfter=after if result.done else None,
    )
    _append(log, record)
    if rate_limited:
        raise DriverExitError(5, RATE_LIMIT_NOTICE)
    if not result.done:
        return 0

    if after["turnCount"] % CHECK_EVERY == 0:
        room = fetch_room(session, room_id)
        fetched = room_after(room, room_static(room), "refetch")
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
            raise DriverExitError(8, "누적값과 조회값이 다르다 — 오케스트레이터에게 보고")
    if ending is not None:
        return 3
    reached = new_milestones(rules, after, reached_milestones(snapshot_log, room_id))
    if reached:
        raise _pause(
            log, snapshot_log, room_id, after["turnCount"], "milestone", threshold=max(reached), crossed=reached
        )
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
    ap.add_argument("--replica", help="복제본 디렉터리(칸 이름 표) — 방 만들기·턴에 필수")
    ap.add_argument("--content-id", help="방 만들기: 작품 id")
    ap.add_argument("--setup", type=int, default=0, help="방 만들기: 시작설정 인덱스")
    ap.add_argument("--room")
    ap.add_argument("--say")
    ap.add_argument("--shortcut", help="단축어 이름 — 화면 버튼과 같이 프롬프트 원문과 단축어 id 를 보낸다")
    ap.add_argument("--tag", choices=["보통", "넘김", "프로브"], default="보통", help="로그에만 남긴다")
    ap.add_argument("--set-note", help="보내기 전에 기억 노트를 이 파일 내용으로 덮어쓴다")
    ap.add_argument("--server-log", help="서버 로그(턴에 필수) — Gemini 429 감지")
    ap.add_argument("--stop-file", help="보내기 전에 이 파일이 있으면 보내지 않고 종료 코드 10")
    ap.add_argument("--pause-at", help="방 턴 수 목록(쉼표) — 그 턴 수에서 다음 턴을 보내기 전에 한 번 종료 코드 10")
    ap.add_argument("--milestone-stat", default="상영회까지", help="첫 도달 시 멈출 스탯 이름")
    ap.add_argument("--milestones", default="7,0", help="그 스탯이 처음 이 값 이하가 된 턴 뒤 종료 코드 10(쉼표)")
    ap.add_argument("--rebase", metavar="REASON", help="전체 조회로 누적 기준을 다시 잡는다(사유 기록)")
    ap.add_argument("--state", action="store_true", help="전체 조회로 상태만 출력(기록 안 함)")
    return ap


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    turn = args.say is not None or args.shortcut is not None
    if args.say is not None and args.shortcut is not None:
        ap.error("--say 와 --shortcut 은 함께 쓸 수 없다")
    if (turn or args.content_id) and not args.replica:
        ap.error("방 만들기·턴에는 --replica 가 필요하다")
    if turn and not (args.room and args.server_log):
        ap.error("턴에는 --room·--server-log 가 필요하다")
    log = Path(args.log)
    snapshot_log = Path(args.snapshot_log)
    if log.resolve() == snapshot_log.resolve():
        ap.error("--snapshot-log 는 --log 와 다른 파일이어야 한다")

    def session_factory() -> Session:
        return Session(args.base, args.cred_file, args.cookie_file, log, transport)

    try:
        if args.content_id:
            return create_room(args, session_factory(), log, snapshot_log)
        if not args.room:
            ap.error("--content-id 또는 --room 이 필요하다")
        if args.state:
            room = fetch_room(session_factory(), args.room)
            print(stats_line(room_after(room, room_static(room), "refetch"), room_static(room)))
            return 0
        if args.rebase:
            after, static = rebase(session_factory(), log, snapshot_log, args.room, args.rebase, pause_rules(args))
            print(stats_line(after, static))
            return 0
        if turn:
            return play_turn(args, session_factory, log, snapshot_log)
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
