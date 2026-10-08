"""측정 드라이버를 가짜 서버(`httpx.MockTransport`)와 가짜 DB 읽기로 돌린다 — LLM·실서버 없이 종료 코드 경로, 쿠키 재사용,
누적 상태, 은폐(시뮬레이터 로그에 요약·단축어 원문이 없음), 방 고정값 기록, 드라이버 DB 와 서버가 같은지 확인을 본다.
마지막 테스트 하나만 실제 테스트 DB 로 기본 DB 읽기를 돈다."""

import json
import os
import stat
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import chat_play
from api.chat.router import InjectedPersona
from api.core.config import settings
from api.db.models.chat import ChatRoom
from factories import _add_named_media_cell, _story_with_setup
from replay.room_fixed import RoomFixed

ROOM_ID = "11111111-1111-4111-8111-111111111111"
CONTENT_ID = "22222222-2222-4222-8222-222222222222"
SETUP_ID = "33333333-3333-4333-8333-333333333333"
STAT_DAYS = "44444444-4444-4444-8444-444444444444"
STAT_LIKE = "55555555-5555-4555-8555-555555555555"
ENDING_ID = "66666666-6666-4666-8666-666666666666"
SHORTCUT_ID = "77777777-7777-4777-8777-777777777777"
CELL_ID = uuid.UUID("88888888-8888-4888-8888-888888888888")
SETUP_ROW_ID = uuid.UUID("99999999-9999-4999-8999-999999999999")
VERSION_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PERSONA_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
SHORTCUT_PROMPT = "{{user}}는 며칠을 건너뛴다(비공개 원문)"
SUMMARY_TEXT = "요약 본문 — 시뮬레이터가 보면 안 된다"
PERSONA = InjectedPersona(name="하늘", gender="female", description="밤에만 글을 쓴다(프로필 전문)")


def _sse(*events: dict[str, Any]) -> bytes:
    return b"".join(b"data: " + json.dumps(e, ensure_ascii=False).encode() + b"\n\n" for e in events)


class FakeServer:
    """방 하나를 가진 가짜 API 와 그 방을 비추는 가짜 드라이버 DB. 테스트가 다음 턴 응답(`turns`)·401 횟수·조회 값
    어긋남·DB 쪽 어긋남(`db_changes`)을 정한다."""

    def __init__(self) -> None:
        self.content_type = "story"
        self.turn_count = 0
        self.stats: dict[str, float] = {STAT_DAYS: 28, STAT_LIKE: 20}
        self.ending = False
        self.note = ""
        self.persona: InjectedPersona | None = None
        self.calls: list[tuple[str, str, Any, str | None]] = []
        self.turns: list[httpx.Response] = []
        self.unauthorized = 0
        self.login_response: httpx.Response | None = None
        self.db_reads: list[str] = []
        self.db_room_missing = False
        self.db_changes: dict[str, Any] = {}

    def room(self) -> dict[str, Any]:
        return {
            "id": ROOM_ID,
            "contentId": CONTENT_ID,
            "contentType": self.content_type,
            "name": "방",
            "startingSetupId": SETUP_ID,
            "turnCount": self.turn_count,
            "endingReached": self.ending,
            "stats": dict(self.stats),
            "messages": [
                {"id": "m0", "role": "assistant", "content": "{{user}}, 왔어?\n\n{{img::" + str(CELL_ID) + "}}"}
            ],
            "contentSnapshot": {
                "stats": [
                    {"id": STAT_DAYS, "name": "마감까지", "unit": "일", "description": "비공개 설명"},
                    {"id": STAT_LIKE, "name": "서진 호감도", "unit": "", "description": "비공개 설명"},
                ],
                "endings": [{"id": ENDING_ID, "name": "새 학기의 첫 장", "judgmentPrompt": "비공개 판정문"}],
                "shortcuts": [{"id": SHORTCUT_ID, "name": "며칠 뒤로", "description": "", "prompt": SHORTCUT_PROMPT}],
                "suggestedReplies": ["{{user}}입니다"],
                "pinnedStartingSetupId": str(SETUP_ROW_ID),
            },
            "personaId": str(PERSONA_ID) if self.persona is not None else None,
            "personaName": self.persona.name if self.persona is not None else None,
            "defaultUserName": "여행자",
            "contentName": "등대지기",
            "chatModel": "sonnet",
            "effectiveChatModel": "gemini",
        }

    def read_db(self, room_id: str) -> chat_play.DbRoom | None:
        self.db_reads.append(room_id)
        if self.db_room_missing:
            return None
        fields: dict[str, Any] = {
            "content_version_id": VERSION_ID,
            "starting_setup_entity_id": uuid.UUID(SETUP_ID),
            "pinned_starting_setup_id": SETUP_ROW_ID,
            "chat_model": "sonnet",
            "persona_id": PERSONA_ID if self.persona is not None else None,
            "persona_name": self.persona.name if self.persona is not None else None,
            "default_user_name": "여행자",
            "persona": self.persona,
        }
        turn_count = self.db_changes.get("turn_count", self.turn_count)
        fields.update({k: v for k, v in self.db_changes.items() if k != "turn_count"})
        return chat_play.DbRoom(
            fixed=RoomFixed(**fields), turn_count=turn_count, cell_labels={str(CELL_ID): "서진/옥상"}
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.calls.append((request.method, path, body, request.headers.get("cookie")))
        if path == "/auth/login":
            if self.login_response is not None:
                return self.login_response
            return httpx.Response(204, headers={"set-cookie": "session_id=fresh-cookie; Path=/; HttpOnly"})
        if self.unauthorized > 0:
            self.unauthorized -= 1
            return httpx.Response(401, json={"detail": "Not authenticated"})
        if path == f"/contents/{CONTENT_ID}":
            return httpx.Response(
                200,
                json={
                    "type": self.content_type,
                    "name": "등대지기",
                    "versionNumber": 6,
                    "startingSetups": [{"id": SETUP_ID, "name": "첫 기획 회의"}],
                },
            )
        if path == "/chat-rooms" and request.method == "POST":
            return httpx.Response(201, json=self.room())
        if path == f"/chat-rooms/{ROOM_ID}/play-guide":
            return httpx.Response(200, json={"playGuide": "{{user}}가 고른다"})
        if path == f"/chat-rooms/{ROOM_ID}" and request.method == "GET":
            return httpx.Response(200, json=self.room())
        if path == f"/chat-rooms/{ROOM_ID}/memory/note":
            assert body is not None
            self.note = body["note"].strip()
            return httpx.Response(200, json=self._memory())
        if path == f"/chat-rooms/{ROOM_ID}/memory":
            return httpx.Response(200, json=self._memory())
        if path == f"/chat-rooms/{ROOM_ID}/messages":
            response = self.turns.pop(0)
            if response.status_code == 200 and b'"done"' in response.content:
                self.turn_count += 1
            return response
        raise AssertionError(f"모르는 요청 {request.method} {path}")

    def _memory(self) -> dict[str, Any]:
        summary = {"text": SUMMARY_TEXT, "source": "auto", "canRevert": False, "updatedAt": "2026-10-05T00:00:00Z"}
        return {"note": self.note, "summary": summary, "version": 1, "rolledBackAt": None, "limits": {}}

    def paths(self, method: str, suffix: str) -> list[Any]:
        return [c for c in self.calls if c[0] == method and c[1].endswith(suffix)]


def _turn(
    *events: dict[str, Any], done: bool = True, image_id: str | None = None, message_id: str = "x"
) -> httpx.Response:
    tail = [{"type": "done", "finalMessage": {"id": message_id, "content": "", "imageId": image_id}}] if done else []
    return httpx.Response(200, content=_sse(*events, *tail), headers={"content-type": "text/event-stream"})


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(chat_play, "MIN_GAP", 0.0)
    cred = tmp_path / "cred.json"
    cred.write_text(json.dumps({"email": "sim@example.com", "password": "pw"}))
    os.chmod(cred, 0o600)
    server_log = tmp_path / "server.log"
    server_log.write_text("")
    return {
        "dir": tmp_path,
        "server": FakeServer(),
        "log": tmp_path / "sim.jsonl",
        "snap": tmp_path / "snap.jsonl",
        "cookie": tmp_path / "cookie",
        "server_log": server_log,
        "common": [
            "--base",
            "http://127.0.0.1:8015",
            "--cred-file",
            str(cred),
            "--cookie-file",
            str(tmp_path / "cookie"),
            "--log",
            str(tmp_path / "sim.jsonl"),
            "--snapshot-log",
            str(tmp_path / "snap.jsonl"),
        ],
    }


def _main(run: dict[str, Any], *extra: str) -> int:
    server: FakeServer = run["server"]
    return chat_play.main(
        [*run["common"], *extra], transport=httpx.MockTransport(server.handler), room_fixed_reader=server.read_db
    )


def _say(run: dict[str, Any], text: str = "안녕", *extra: str) -> int:
    return _main(run, "--room", ROOM_ID, "--say", text, *extra)


def _say_watching(run: dict[str, Any], text: str = "안녕") -> int:
    """서버 로그를 보며 한 턴 — 그 방의 Gemini 429 흔적이 있으면 멈춘다."""
    return _say(run, text, "--server-log", str(run["server_log"]))


def _records(path: Path, kind: str | None = None) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [r for r in rows if kind is None or r.get("kind") == kind]


def _create(run: dict[str, Any]) -> None:
    assert _main(run, "--content-id", CONTENT_ID, "--setup", "0") == 0


# ── 방 만들기 · 화면 글 · 방 고정값 · 쿠키 ───────────────────────────────────


def test_create_room_renders_author_text_like_the_screen_and_hides_private_fields(
    run: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    _create(run)
    out = capsys.readouterr().out
    meta = _records(run["log"], "meta")[0]
    assert (meta["startingSetupId"], meta["pinnedStartingSetupId"]) == (SETUP_ID, str(SETUP_ROW_ID))
    # 최신 발행본 번호는 방 버전이 아니라서 남기지 않는다 — 방 버전은 방 고정값의 버전 id 로 남는다.
    assert "versionNumber" not in meta
    opening = _records(run["log"], "opening")[0]
    assert opening["messages"] == ["여행자, 왔어?\n\n[그림: 서진/옥상]"]
    assert opening["suggestedReplies"] == ["여행자입니다"]
    assert opening["playGuide"] == "여행자가 고른다"
    assert opening["roomAfter"]["stats"] == {"마감까지": 28, "서진 호감도": 20}
    # 비공개 필드는 시뮬레이터 쪽 어디에도 없다.
    for leaked in ("비공개", SHORTCUT_PROMPT):
        assert leaked not in run["log"].read_text()
        assert leaked not in out
    assert "비공개 원문" in run["snap"].read_text()


def test_room_static_records_the_fixed_values_and_the_full_persona(run: dict[str, Any]) -> None:
    run["server"].persona = PERSONA
    _create(run)
    static = _records(run["snap"], "roomStatic")[0]
    assert {k: static[k] for k in RoomFixed.RECORD_KEYS} == {
        "contentVersionId": str(VERSION_ID),
        "startingSetupEntityId": SETUP_ID,
        "pinnedStartingSetupId": str(SETUP_ROW_ID),
        "chatModel": "sonnet",
        "personaId": str(PERSONA_ID),
        "personaName": "하늘",
        "defaultUserName": "여행자",
        "userName": "하늘",
        "persona": {"name": "하늘", "gender": "female", "description": "밤에만 글을 쓴다(프로필 전문)"},
    }
    # 서버가 실제로 쓰는 모델은 방 칸과 다를 수 있다 — 둘 다 남긴다.
    assert static["effectiveChatModel"] == "gemini"
    assert RoomFixed.from_record(static) is not None
    # 프로필 전문은 시뮬레이터 로그에 없다.
    assert "프로필 전문" not in run["log"].read_text()
    assert _records(run["log"], "opening")[0]["messages"][0].startswith("하늘, 왔어?")


def test_rebase_records_the_fixed_values_again(run: dict[str, Any]) -> None:
    _create(run)
    run["server"].turn_count = 2  # 사람이 화면에서 2턴
    assert _main(run, "--room", ROOM_ID, "--rebase", "사람 구간 끝") == 0
    statics = _records(run["snap"], "roomStatic")
    assert len(statics) == 2
    assert statics[1]["contentVersionId"] == str(VERSION_ID)
    assert run["server"].db_reads == [ROOM_ID, ROOM_ID]


def test_cookie_is_saved_once_and_reused_without_logging_in_again(run: dict[str, Any]) -> None:
    _create(run)
    run["server"].turns = [_turn(), _turn(), _turn()]
    for _ in range(3):
        assert _say(run) == 0
    server = run["server"]
    assert len(server.paths("POST", "/auth/login")) == 1
    assert _records(run["log"], "relogin") == []
    assert run["cookie"].read_text() == "fresh-cookie"
    assert stat.S_IMODE(os.stat(run["cookie"]).st_mode) == 0o600
    turn_calls = server.paths("POST", "/messages")
    assert all(cookie == "session_id=fresh-cookie" for *_, cookie in turn_calls)


def test_401_relogs_in_once_and_resends_the_same_turn(run: dict[str, Any]) -> None:
    _create(run)
    run["log"].write_text("".join(line + "\n" for line in run["log"].read_text().splitlines() if '"login"' not in line))
    run["server"].unauthorized = 1
    run["server"].turns = [_turn()]
    assert _say(run) == 0
    assert len(_records(run["log"], "relogin")) == 1
    assert _records(run["log"], "turn")[0]["done"] is True


def test_second_login_inside_the_limit_window_stops_with_code_2_without_calling_login(run: dict[str, Any]) -> None:
    _create(run)  # 첫 로그인(쿠키 없음)
    run["server"].unauthorized = 1
    assert _say(run) == 2
    assert len(run["server"].paths("POST", "/auth/login")) == 1


def test_login_429_auth_limit_stops_with_code_2(run: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    run["server"].login_response = httpx.Response(
        429, json={"detail": {"code": "AUTH_LIMIT", "retryAfterSeconds": 900}}
    )
    assert _main(run, "--content-id", CONTENT_ID) == 2
    assert "AUTH_LIMIT" in capsys.readouterr().out


def test_credential_file_with_loose_permissions_is_refused(run: dict[str, Any]) -> None:
    os.chmod(run["dir"] / "cred.json", 0o644)
    assert _main(run, "--content-id", CONTENT_ID) == 2
    assert run["server"].calls == []


# ── 거부: 운영 DB · 다른 DB · 캐릭터 작품 ────────────────────────────────────


def test_production_database_is_refused_before_any_request(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 읽기 함수를 주지 않으면 드라이버가 자기 DB 를 연다 — 그 전에, 네트워크보다 먼저 호스트를 본다.
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://u:p@postgres:5432/ai_character_chat")
    server: FakeServer = run["server"]
    code = chat_play.main(
        [*run["common"], "--content-id", CONTENT_ID], transport=httpx.MockTransport(server.handler)
    )
    assert code == 2
    assert server.calls == []
    assert "'postgres'" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("missing", "changes"),
    [
        pytest.param(True, {}, id="room-row-missing"),
        pytest.param(False, {"persona_id": uuid.UUID(int=5)}, id="persona-differs"),
        pytest.param(False, {"turn_count": 7}, id="turn-count-differs"),
        pytest.param(False, {"pinned_starting_setup_id": uuid.UUID(int=6)}, id="pinned-setup-differs"),
    ],
)
def test_driver_database_that_is_not_the_servers_is_refused_before_recording(
    run: dict[str, Any], missing: bool, changes: dict[str, Any]
) -> None:
    server: FakeServer = run["server"]
    server.db_room_missing = missing
    server.db_changes = changes
    assert _main(run, "--content-id", CONTENT_ID, "--setup", "0") == 2
    # 방 고정값과 오프닝을 남기지 않는다 — 다른 DB 의 값을 이 방의 것으로 기록하게 된다.
    assert _records(run["snap"], "roomStatic") == []
    assert _records(run["log"], "opening") == []


def test_rebase_against_another_database_is_refused(run: dict[str, Any]) -> None:
    _create(run)
    run["server"].turn_count = 3
    run["server"].db_changes = {"turn_count": 1}
    assert _main(run, "--room", ROOM_ID, "--rebase", "사람 구간 끝") == 2
    assert _records(run["log"], "rebase") == []


def test_character_content_is_refused_before_a_room_is_made(run: dict[str, Any]) -> None:
    run["server"].content_type = "character"
    assert _main(run, "--content-id", CONTENT_ID) == 2
    assert run["server"].paths("POST", "/chat-rooms") == []
    assert run["server"].db_reads == []


def test_character_room_is_refused_on_rebase(run: dict[str, Any]) -> None:
    run["server"].content_type = "character"
    assert _main(run, "--room", ROOM_ID, "--rebase", "x") == 2
    assert _records(run["snap"], "roomStatic") == []


# ── 한 턴 · 누적 상태 · 은폐 ─────────────────────────────────────────────────


def test_turn_accumulates_sse_state_and_keeps_summary_out_of_the_simulator_log(
    run: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    _create(run)
    capsys.readouterr()
    run["server"].turns = [
        _turn(
            {"type": "token", "delta": "응답"},
            {"type": "statChange", "statId": STAT_LIKE, "newValue": 23},
            image_id=str(CELL_ID),
        )
    ]
    assert _say(run, "안녕", "--tag", "아무 꼬리표") == 0
    out = capsys.readouterr().out
    turn = _records(run["log"], "turn")[0]
    assert turn["roomAfter"] == {
        "turnCount": 1,
        "stats": {"마감까지": 28, "서진 호감도": 23},
        "endingReached": False,
        "source": "sse",
    }
    assert (turn["tag"], turn["imageLabel"], turn["reply"]) == ("아무 꼬리표", "서진/옥상", "응답")
    assert turn["memory"]["summaryLen"] == len(SUMMARY_TEXT)
    assert "[그림: 서진/옥상]" in out
    # 요약 전문은 시뮬레이터가 못 읽는 파일에만, 바뀐 턴에만.
    assert SUMMARY_TEXT not in run["log"].read_text() and SUMMARY_TEXT not in out
    snapshot = _records(run["snap"], "memorySnapshot")[0]
    assert (snapshot["summary"], snapshot["turn"]) == (SUMMARY_TEXT, 1)
    assert isinstance(turn["ttftMs"], int)
    # 매 턴 방 전체를 다시 받지 않고 DB 도 읽지 않는다(만들 때 한 번뿐).
    assert run["server"].paths("GET", f"/chat-rooms/{ROOM_ID}") == []
    assert len(run["server"].db_reads) == 1


def test_client_turn_is_the_server_turn_number_even_after_a_lost_turn_and_human_turns(run: dict[str, Any]) -> None:
    # 프롬프트 덤프와 리플레이는 턴 번호를 "서버 턴 수 + 1" 로 센다. 유실 턴(200 인데 done 없음)이나 사람이 화면에서
    # 친 턴을 드라이버가 성공 수로 세면 그 뒤 번호가 덤프와 어긋난다.
    _create(run)
    server: FakeServer = run["server"]
    server.turns = [_turn(), _turn({"type": "error", "message": "생성 실패"}, done=False), _turn(), _turn()]
    assert _say(run, "1") == 0
    assert _say(run, "2") == 0  # 유실
    assert _say(run, "2 다시") == 0
    server.turn_count += 2  # 사람이 화면에서 2턴
    assert _main(run, "--room", ROOM_ID, "--rebase", "사람 구간 끝") == 0
    assert _say(run, "5") == 0
    turns = _records(run["log"], "turn")
    assert [(t["turnBefore"], t["clientTurn"]) for t in turns] == [(0, 1), (1, 2), (1, 2), (4, 5)]


def test_turn_line_records_the_shortcut_id_and_the_assistant_message_id(run: dict[str, Any]) -> None:
    _create(run)
    run["server"].turns = [_turn(message_id="msg-1"), _turn(message_id="msg-2")]
    assert _say(run) == 0
    assert _main(run, "--room", ROOM_ID, "--shortcut", "며칠 뒤로") == 0
    plain, shortcut = _records(run["log"], "turn")
    assert (plain["shortcutId"], plain["assistantMessageId"]) == (None, "msg-1")
    assert (shortcut["shortcutId"], shortcut["assistantMessageId"]) == (SHORTCUT_ID, "msg-2")


def test_records_keep_the_keys_the_pair_judge_reads(run: dict[str, Any]) -> None:
    # 쌍 판정 도구는 오프닝 `messages`, 턴 `clientTurn`·`userText`·`reply` 로 원래 대화를 다시 짓는다. 단축어 턴의
    # `userText` 는 비운다 — 시뮬레이터에게 단축어 원문을 숨기는 설계다.
    _create(run)
    run["server"].turns = [_turn({"type": "token", "delta": "답 하나"}), _turn({"type": "token", "delta": "답 둘"})]
    assert _say(run, "첫 말") == 0
    assert _main(run, "--room", ROOM_ID, "--shortcut", "며칠 뒤로") == 0
    opening = _records(run["log"], "opening")[0]
    assert opening["messages"] == ["여행자, 왔어?\n\n[그림: 서진/옥상]"]
    turns = _records(run["log"], "turn")
    assert [(t["clientTurn"], t["userText"], t["reply"]) for t in turns] == [(1, "첫 말", "답 하나"), (2, None, "답 둘")]


def test_memory_snapshot_is_written_only_when_note_or_summary_changes(run: dict[str, Any]) -> None:
    _create(run)
    run["server"].turns = [_turn(), _turn()]
    assert _say(run) == 0
    assert _say(run) == 0
    assert len(_records(run["snap"], "memorySnapshot")) == 1


def test_note_is_printed_every_turn_even_when_unchanged(
    run: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    # 시뮬레이터는 매 턴 출력에서 지금 노트를 본다고 가정하므로, 바뀌지 않은 턴에도 노트를 보여 준다.
    _create(run)
    note = run["dir"] / "note.txt"
    note.write_text("서진: 편집 담당")
    run["server"].turns = [_turn(), _turn()]
    assert _say(run, "안녕", "--set-note", str(note)) == 0
    capsys.readouterr()
    assert _say(run) == 0
    assert "[기억 노트]\n서진: 편집 담당" in capsys.readouterr().out


def test_shortcut_sends_prompt_and_id_but_logs_only_the_name(
    run: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    _create(run)
    capsys.readouterr()
    run["server"].turns = [_turn({"type": "token", "delta": "며칠 뒤"})]
    assert _main(run, "--room", ROOM_ID, "--shortcut", "며칠 뒤로") == 0
    sent = run["server"].paths("POST", "/messages")[0][2]
    assert sent == {"content": "여행자는 며칠을 건너뛴다(비공개 원문)", "shortcutId": SHORTCUT_ID}
    turn = _records(run["log"], "turn")[0]
    assert (turn["userText"], turn["shortcut"]) == (None, "며칠 뒤로")
    assert "비공개 원문" not in run["log"].read_text()
    assert "비공개 원문" not in capsys.readouterr().out


def test_set_note_puts_before_the_turn_and_hashes_the_saved_note(
    run: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    _create(run)
    capsys.readouterr()
    note = run["dir"] / "note.txt"
    note.write_text("  서진: 편집 담당  \n")
    run["server"].turns = [_turn()]
    assert _say(run, "안녕", "--set-note", str(note)) == 0
    methods = [
        c[0] + " " + c[1].rsplit("/", 1)[-1] for c in run["server"].calls if "memory" in c[1] or "messages" in c[1]
    ]
    assert methods == ["PUT note", "GET memory", "POST messages"]
    update = _records(run["log"], "noteUpdate")[0]
    assert (update["note"], update["length"]) == ("서진: 편집 담당", 9)
    assert update["sha256"] == chat_play._sha("서진: 편집 담당")
    assert _records(run["log"], "turn")[0]["memory"]["noteSha"] == update["sha256"]
    assert "[기억 노트]\n서진: 편집 담당" in capsys.readouterr().out


def test_note_over_the_limit_exits_9_before_any_request(run: dict[str, Any]) -> None:
    _create(run)
    before = len(run["server"].calls)
    note = run["dir"] / "note.txt"
    note.write_text("가" * 1001)
    assert _say(run, "안녕", "--set-note", str(note)) == 9
    assert len(run["server"].calls) == before


# ── 종료 코드 ───────────────────────────────────────────────────────────────


def test_turn_in_progress_409_exits_6(run: dict[str, Any]) -> None:
    _create(run)
    run["server"].turns = [httpx.Response(409, json={"detail": {"code": "CHAT_TURN_IN_PROGRESS"}})]
    assert _say(run) == 6


@pytest.mark.parametrize("code", ["CLOVER_REQUIRED", "CLOVER_CONFIRM_REQUIRED"])
def test_clover_429_exits_7_without_sleeping_until_midnight(run: dict[str, Any], code: str) -> None:
    _create(run)
    run["server"].turns = [httpx.Response(429, json={"detail": {"code": code, "retryAfterSeconds": 50000}})]
    assert _say(run) == 7
    assert not (run["dir"] / ".retry_at").exists()


def test_burst_429_exits_4_and_remembers_retry_after(run: dict[str, Any]) -> None:
    _create(run)
    run["server"].turns = [httpx.Response(429, json={"detail": {"code": "USER_LIMIT", "retryAfterSeconds": 30}})]
    assert _say(run) == 4
    assert (run["dir"] / ".retry_at").exists()
    assert _records(run["log"], "turn")[0]["appCode"] == "USER_LIMIT"


def test_403_exits_2(run: dict[str, Any]) -> None:
    _create(run)
    run["server"].turns = [httpx.Response(403, json={"detail": {"code": "CONSENT_REQUIRED"}})]
    assert _say(run) == 2


def test_ending_exits_3_and_shows_the_rendered_epilogue(
    run: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    _create(run)
    capsys.readouterr()
    epilogue = "{{user}}의 첫 장 {{img::" + str(CELL_ID) + "}}"
    run["server"].turns = [_turn({"type": "endingReached", "endingId": ENDING_ID, "epilogue": epilogue})]
    assert _say(run) == 3
    ending = _records(run["log"], "turn")[0]["ending"]
    assert ending == {"id": ENDING_ID, "name": "새 학기의 첫 장", "epilogue": "여행자의 첫 장 [그림: 서진/옥상]"}


def test_gemini_429_in_the_server_log_for_this_room_exits_5(
    run: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    _create(run)
    server = run["server"]

    def turn_with_429(request: httpx.Request) -> httpx.Response:
        with run["server_log"].open("a") as f:
            f.write(f"WARNING 대화방 {ROOM_ID} 판정 실패: 429 RESOURCE_EXHAUSTED. quota\n")
        return _turn()

    original = server.handler
    server.handler = lambda r: turn_with_429(r) if r.url.path.endswith("/messages") else original(r)
    assert _say_watching(run) == 5
    assert chat_play.RATE_LIMIT_NOTICE in capsys.readouterr().out


def test_server_log_is_not_read_unless_given(run: dict[str, Any]) -> None:
    # 서버 로그 감시는 선택이다 — 주지 않으면 그 방의 429 흔적이 있어도 턴은 그대로 끝난다.
    _create(run)
    with run["server_log"].open("a") as f:
        f.write(f"WARNING 대화방 {ROOM_ID} 판정 실패: 429 RESOURCE_EXHAUSTED. quota\n")
    run["server"].turns = [_turn()]
    assert _say(run) == 0
    assert "serverLogOffsetAfter" not in _records(run["log"], "turn")[0]


def test_gemini_429_logged_after_the_previous_turn_stops_the_next_turn_before_sending(run: dict[str, Any]) -> None:
    _create(run)
    run["server"].turns = [_turn()]
    assert _say_watching(run) == 0
    with run["server_log"].open("a") as f:
        f.write(f"WARNING 대화방 {ROOM_ID} 요약 접기 실패 (커서 x): 429 RESOURCE_EXHAUSTED\n")
    sent_before = len(run["server"].paths("POST", "/messages"))
    assert _say_watching(run) == 5
    assert len(run["server"].paths("POST", "/messages")) == sent_before


def test_app_429_access_lines_and_other_rooms_do_not_count_as_gemini_429(run: dict[str, Any]) -> None:
    with run["server_log"].open("a") as f:
        f.write(f'INFO: 127.0.0.1:1 - "POST /chat-rooms/{ROOM_ID}/messages HTTP/1.1" 429 Too Many Requests\n')
        f.write("WARNING 대화방 00000000-0000-4000-8000-000000000000 판정 실패: 429 RESOURCE_EXHAUSTED\n")
    hit, _ = chat_play.scan_gemini_429(run["server_log"], 0, ROOM_ID)
    assert hit is False


def test_numbers_429_in_timestamps_and_token_counts_are_not_gemini_429(run: dict[str, Any]) -> None:
    # 서버 로그의 모든 줄 앞에는 밀리초까지 시각이 붙고, 사용량 줄에는 토큰 수가 찍힌다 — 둘 다 숫자 429 가 될 수 있다.
    usage = (
        "WARNING gemini_usage call_site=chat_generate model=gemini-3.5-flash-lite prompt_tokens=13223 "
        f"cached_content_tokens=None candidates_tokens=429 thoughts_tokens=None total_tokens=13652 user_id=u room_id={ROOM_ID}"
    )
    with run["server_log"].open("a") as f:
        f.write(f"2026-10-05T15:51:43.580+0900 {usage}\n")
        f.write(f"2026-10-05T15:51:12.429+0900 {usage.replace('candidates_tokens=429', 'candidates_tokens=589')}\n")
        f.write(f"2026-10-05T15:51:12.429+0900 WARNING 대화방 {ROOM_ID} 판정 실패 — 이번 턴의 판정을 건너뛴다: \n")
    hit, _ = chat_play.scan_gemini_429(run["server_log"], 0, ROOM_ID)
    assert hit is False
    with run["server_log"].open("a") as f:
        f.write(
            f"2026-10-05T15:52:00.100+0900 WARNING 대화방 {ROOM_ID} 스탯 판정 실패 — 이번 턴의 스탯·엔딩 판정을 건너뛴다: "
            "Gemini generate_structured() call failed: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429}}\n"
        )
    hit, _ = chat_play.scan_gemini_429(run["server_log"], 0, ROOM_ID)
    assert hit is True


def test_gemini_429_without_a_json_body_still_counts_as_gemini_429(run: dict[str, Any]) -> None:
    # 429 본문이 JSON 이 아니면 SDK 가 상태 자리를 HTTP 사유 문구로 채워 RESOURCE_EXHAUSTED 가 없다. 서버는 이 예외를
    # "… call failed: {예외}" 로 감싸 싣고, 예외 문자열은 상태 코드로 시작한다.
    with run["server_log"].open("a") as f:
        f.write(
            f"2026-10-05T15:52:00.100+0900 WARNING 대화방 {ROOM_ID} 판정 실패 — 이번 턴의 판정을 건너뛴다: "
            "Gemini generate_structured() call failed: 429 Too Many Requests. <html>quota</html>\n"
        )
    hit, _ = chat_play.scan_gemini_429(run["server_log"], 0, ROOM_ID)
    assert hit is True


def test_other_gemini_status_codes_starting_with_429_digits_are_not_gemini_429(run: dict[str, Any]) -> None:
    with run["server_log"].open("a") as f:
        f.write(
            f"2026-10-05T15:52:00.429+0900 WARNING 대화방 {ROOM_ID} 판정 실패 — 이번 턴의 판정을 건너뛴다: "
            "Gemini generate_structured() call failed: 4290 Odd. candidates_tokens=429\n"
        )
    hit, _ = chat_play.scan_gemini_429(run["server_log"], 0, ROOM_ID)
    assert hit is False


def test_gemini_429_logged_while_the_note_is_saved_is_not_skipped(run: dict[str, Any]) -> None:
    # 사전 검사 뒤 노트 저장·기억 조회 사이에 찍힌 줄(직전 턴의 요약 접기 실패)도 이 턴의 사후 검사가 본다.
    _create(run)
    run["server"].turns = [_turn(), _turn()]
    assert _say_watching(run) == 0
    server = run["server"]
    original: Callable[[httpx.Request], httpx.Response] = server.handler

    def memory_with_429(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/memory") and request.method == "GET":
            with run["server_log"].open("a") as f:
                f.write(
                    f"WARNING 대화방 {ROOM_ID} 요약 접기 실패 — 다음 턴 뒤에 다시 시도한다: 429 RESOURCE_EXHAUSTED\n"
                )
        return original(request)

    server.handler = memory_with_429
    assert _say_watching(run) == 5


# ── 대조 · 정지 · 유실 ───────────────────────────────────────────────────────


def test_mismatch_at_the_25th_turn_check_exits_8(run: dict[str, Any]) -> None:
    _create(run)
    server = run["server"]
    server.turns = [_turn() for _ in range(25)]
    for _ in range(24):
        assert _say(run) == 0
    server.stats[STAT_LIKE] = 99  # 사람 턴처럼 누적에 없는 변화
    assert _say(run) == 8
    check = _records(run["log"], "check")[0]
    assert (check["ok"], check["roomAfter"]) == (False, None)
    assert server.paths("GET", f"/chat-rooms/{ROOM_ID}")[0][1] == f"/chat-rooms/{ROOM_ID}"


def test_matching_25th_turn_check_becomes_the_new_baseline(run: dict[str, Any]) -> None:
    _create(run)
    run["server"].turns = [_turn() for _ in range(25)]
    for _ in range(25):
        assert _say(run) == 0
    check = _records(run["log"], "check")[0]
    assert check["ok"] is True and check["roomAfter"]["source"] == "refetch"


def test_check_every_sets_the_check_interval(run: dict[str, Any]) -> None:
    _create(run)
    run["server"].turns = [_turn() for _ in range(4)]
    for _ in range(4):
        assert _say(run, "x", "--check-every", "2") == 0
    assert [c["accumulated"]["turnCount"] for c in _records(run["log"], "check")] == [2, 4]


def test_stop_file_pauses_with_10_before_any_request(run: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    _create(run)
    before = len(run["server"].calls)
    stop_file = run["dir"] / "STOP"
    stop_file.write_text("")
    assert _say(run, "안녕", "--stop-file", str(stop_file)) == 10
    assert len(run["server"].calls) == before
    assert chat_play.PAUSE_NOTICE in capsys.readouterr().out
    assert [sorted(r) for r in _records(run["log"], "pause")] == [["at", "kind", "roomId", "turnCount"]]
    assert _records(run["snap"], "pause")[0]["trigger"] == "stop-file"


def test_pause_at_uses_the_room_turn_count_and_pauses_only_once(run: dict[str, Any]) -> None:
    _create(run)
    run["server"].turns = [_turn(), _turn()]
    assert _say(run, "1", "--pause-at", "1") == 0
    assert _say(run, "2", "--pause-at", "1") == 10
    assert _say(run, "2", "--pause-at", "1") == 0
    assert [r["turnBefore"] for r in _records(run["log"], "turn")] == [0, 1]


def test_pause_at_counts_human_turns_after_a_rebase(run: dict[str, Any]) -> None:
    """사람 턴은 이 로그에 없다 — 재기준 뒤의 방 턴 수로 세야 한다."""
    _create(run)
    run["server"].turn_count = 3  # 사람이 화면에서 3턴
    assert _main(run, "--room", ROOM_ID, "--rebase", "사람 구간 끝") == 0
    assert _say(run, "x", "--pause-at", "3") == 10


def test_lost_turn_is_followed_by_a_rebase_before_the_next_turn(run: dict[str, Any]) -> None:
    _create(run)
    run["server"].turns = [_turn({"type": "error", "message": "생성 실패"}, done=False), _turn()]
    assert _say(run) == 0
    assert _records(run["log"], "turn")[0]["roomAfter"] is None
    assert _say(run) == 0
    rebase = _records(run["log"], "rebase")[0]
    assert rebase["reason"] == "유실 턴 뒤" and rebase["roomAfter"]["source"] == "refetch"
    assert _records(run["log"], "turn")[1]["roomAfter"]["turnCount"] == 1


def test_unfinished_turn_keeps_streamed_pieces_out_of_the_reply_the_pair_judge_reads(run: dict[str, Any]) -> None:
    # 유실 턴과 그 재시도는 같은 턴 번호다. 쌍 판정 도구는 `userText` 와 `reply` 가 둘 다 있는 줄을 그 번호의 대화로
    # 읽으므로, 완료 없이 끝난 턴의 조각이 `reply` 에 있으면 같은 번호에 응답이 둘 생긴다.
    _create(run)
    run["server"].turns = [
        _turn({"type": "token", "delta": "반쯤 쓴"}, {"type": "error", "message": "생성 실패"}, done=False),
        _turn({"type": "token", "delta": "경고 전 조각"}, {"type": "policyWarning", "message": "경고"}, done=False),
        _turn({"type": "token", "delta": "완성된 답"}),
    ]
    for _ in range(3):
        assert _say(run, "같은 말") == 0
    lost, warned, retry = turns = _records(run["log"], "turn")
    assert (lost["reply"], lost["partialReply"]) == ("", "반쯤 쓴")
    assert (warned["reply"], warned["partialReply"]) == ("", "경고 전 조각")
    assert lost["clientTurn"] == warned["clientTurn"] == retry["clientTurn"] == 1
    assert [t for t in turns if t.get("userText") and t.get("reply")] == [retry]


def test_connection_lost_mid_stream_leaves_a_turn_line_and_the_next_run_rebases(run: dict[str, Any]) -> None:
    # 줄 없이 끝나면 다음 실행이 직전 기준을 그대로 믿어, 서버가 그 턴을 마쳤을 때 턴 수·스탯이 밀린 채 기록된다.
    _create(run)
    server = run["server"]
    original: Callable[[httpx.Request], httpx.Response] = server.handler

    def broken(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/messages"):
            return original(request)
        server.handler = original
        server.turn_count += 1  # 서버는 그 턴을 끝까지 마쳤다

        def chunks() -> Iterator[bytes]:
            yield _sse({"type": "token", "delta": "끊기기 전"})
            raise httpx.ReadError("연결 끊김")

        return httpx.Response(200, content=chunks(), headers={"content-type": "text/event-stream"})

    server.handler = broken
    assert _say(run) == 1
    lost = _records(run["log"], "turn")[0]
    assert (lost["http"], lost["done"], lost["reply"], lost["roomAfter"]) == (None, False, "", None)
    assert lost["failure"].startswith("transport")
    server.turns = [_turn()]
    assert _say(run) == 0
    assert _records(run["log"], "rebase")[0]["reason"] == "유실 턴 뒤"
    assert _records(run["log"], "turn")[1]["turnBefore"] == 1


def test_turn_on_a_room_logged_without_fixed_values_asks_for_a_rebase_first(
    run: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    # 방 고정값을 기록하기 전의 옛 로그로 이어 치는 경우.
    _create(run)
    rows = _records(run["snap"])
    for row in rows:
        for key in (*RoomFixed.RECORD_KEYS, "cellLabels"):
            row.pop(key, None)
    run["snap"].write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    calls_before = len(run["server"].calls)
    assert _say(run) == 2
    assert len(run["server"].calls) == calls_before
    assert "--rebase" in capsys.readouterr().out


# ── 기본 DB 읽기 ────────────────────────────────────────────────────────────


async def test_db_read_returns_turn_count_fixed_values_and_cell_labels_of_the_room_version(
    db_session: AsyncSession,
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="어서 와")
    version_id = content.current_published_version_id
    assert version_id is not None
    cell, _ = await _add_named_media_cell(db_session, version_id, user_id, "서진", "옥상")
    room = ChatRoom(
        user_id=user_id,
        content_id=content.id,
        content_version_id=version_id,
        starting_setup_entity_id=setup.entity_id,
        turn_count=4,
    )
    db_session.add(room)
    await db_session.flush()

    read = await chat_play.read_db_room(db_session, room.id)

    assert read is not None
    assert (read.turn_count, read.fixed.content_version_id, read.fixed.pinned_starting_setup_id) == (
        4,
        version_id,
        setup.id,
    )
    assert read.cell_labels == {str(cell.entity_id): "서진/옥상"}
    assert await chat_play.read_db_room(db_session, uuid.uuid4()) is None
