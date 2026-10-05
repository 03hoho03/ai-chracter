"""장기 턴 측정 드라이버를 가짜 서버(`httpx.MockTransport`)로 돌린다 — LLM·실서버 없이 종료 코드 경로, 쿠키 재사용,
누적 상태, 은폐(시뮬레이터 로그에 요약·단축어 원문이 없음)를 본다."""

import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest

from experiments.filmclub_longturn import chat_play

ROOM_ID = "11111111-1111-4111-8111-111111111111"
CONTENT_ID = "22222222-2222-4222-8222-222222222222"
SETUP_ID = "33333333-3333-4333-8333-333333333333"
STAT_DAYS = "44444444-4444-4444-8444-444444444444"
STAT_LIKE = "55555555-5555-4555-8555-555555555555"
ENDING_ID = "66666666-6666-4666-8666-666666666666"
SHORTCUT_ID = "77777777-7777-4777-8777-777777777777"
CELL_ID = uuid.UUID("88888888-8888-4888-8888-888888888888")
PERSON_ID = "99999999-9999-4999-8999-999999999999"
SCENE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SHORTCUT_PROMPT = "{{user}}는 며칠을 건너뛴다(비공개 원문)"
SUMMARY_TEXT = "요약 본문 — 시뮬레이터가 보면 안 된다"


def _sse(*events: dict[str, Any]) -> bytes:
    return b"".join(b"data: " + json.dumps(e, ensure_ascii=False).encode() + b"\n\n" for e in events)


class FakeServer:
    """방 하나를 가진 가짜 API. 테스트가 다음 턴 응답(`turns`)·401 횟수·조회 값 어긋남을 정한다."""

    def __init__(self) -> None:
        self.turn_count = 0
        self.stats: dict[str, float] = {STAT_DAYS: 28, STAT_LIKE: 20}
        self.ending = False
        self.note = ""
        self.calls: list[tuple[str, str, Any, str | None]] = []
        self.turns: list[httpx.Response] = []
        self.unauthorized = 0
        self.login_response: httpx.Response | None = None

    def room(self) -> dict[str, Any]:
        return {
            "id": ROOM_ID,
            "contentId": CONTENT_ID,
            "contentType": "story",
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
                    {"id": STAT_DAYS, "name": "상영회까지", "unit": "일", "description": "비공개 설명"},
                    {"id": STAT_LIKE, "name": "도희 호감도", "unit": "", "description": "비공개 설명"},
                ],
                "endings": [{"id": ENDING_ID, "name": "다음 작품의 첫 장", "judgmentPrompt": "비공개 판정문"}],
                "shortcuts": [{"id": SHORTCUT_ID, "name": "며칠 뒤로", "description": "", "prompt": SHORTCUT_PROMPT}],
                "suggestedReplies": ["{{user}}입니다"],
                "pinnedStartingSetupId": SETUP_ID,
            },
            "personaName": None,
            "defaultUserName": "민준",
            "contentName": "조감독",
        }

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
                    "name": "조감독",
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


def _turn(*events: dict[str, Any], done: bool = True, image_id: str | None = None) -> httpx.Response:
    tail = [{"type": "done", "finalMessage": {"id": "x", "content": "", "imageId": image_id}}] if done else []
    return httpx.Response(200, content=_sse(*events, *tail), headers={"content-type": "text/event-stream"})


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(chat_play, "MIN_GAP", 0.0)
    replica = tmp_path / "replica"
    replica.mkdir()
    (replica / "media_book_people.json").write_text(json.dumps([{"entity_id": PERSON_ID, "name": "도희"}]))
    (replica / "media_book_scenes.json").write_text(json.dumps([{"entity_id": SCENE_ID, "name": "기획 회의"}]))
    (replica / "media_book_cells.json").write_text(
        json.dumps([{"entity_id": str(CELL_ID), "person_entity_id": PERSON_ID, "scene_entity_id": SCENE_ID}])
    )
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
            "--replica",
            str(replica),
        ],
    }


def _main(run: dict[str, Any], *extra: str) -> int:
    return chat_play.main([*run["common"], *extra], transport=httpx.MockTransport(run["server"].handler))


def _say(run: dict[str, Any], text: str = "안녕", *extra: str) -> int:
    return _main(run, "--room", ROOM_ID, "--server-log", str(run["server_log"]), "--say", text, *extra)


def _records(path: Path, kind: str | None = None) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [r for r in rows if kind is None or r.get("kind") == kind]


def _create(run: dict[str, Any]) -> None:
    assert _main(run, "--content-id", CONTENT_ID, "--setup", "0") == 0


# ── 방 만들기 · 화면 글 · 쿠키 ───────────────────────────────────────────────


def test_create_room_records_version_and_renders_author_text_like_the_screen(
    run: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    _create(run)
    out = capsys.readouterr().out
    meta = _records(run["log"], "meta")[0]
    assert (meta["versionNumber"], meta["startingSetupId"], meta["pinnedStartingSetupId"]) == (6, SETUP_ID, SETUP_ID)
    opening = _records(run["log"], "opening")[0]
    assert opening["messages"] == ["민준, 왔어?\n\n[그림: 도희/기획 회의]"]
    assert opening["suggestedReplies"] == ["민준입니다"]
    assert opening["playGuide"] == "민준이 고른다"
    assert opening["roomAfter"]["stats"] == {"상영회까지": 28, "도희 호감도": 20}
    # 비공개 필드는 시뮬레이터 쪽 어디에도 없다.
    for leaked in ("비공개", SHORTCUT_PROMPT):
        assert leaked not in run["log"].read_text()
        assert leaked not in out
    assert "비공개 원문" in run["snap"].read_text()


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
    assert _say(run, "안녕", "--tag", "넘김") == 0
    out = capsys.readouterr().out
    turn = _records(run["log"], "turn")[0]
    assert turn["roomAfter"] == {
        "turnCount": 1,
        "stats": {"상영회까지": 28, "도희 호감도": 23},
        "endingReached": False,
        "source": "sse",
    }
    assert (turn["tag"], turn["imageLabel"], turn["reply"]) == ("넘김", "도희/기획 회의", "응답")
    assert turn["memory"]["summaryLen"] == len(SUMMARY_TEXT)
    assert "[그림: 도희/기획 회의]" in out
    # 요약 전문은 시뮬레이터가 못 읽는 파일에만, 바뀐 턴에만.
    assert SUMMARY_TEXT not in run["log"].read_text() and SUMMARY_TEXT not in out
    snapshot = _records(run["snap"], "memorySnapshot")[0]
    assert (snapshot["summary"], snapshot["turn"]) == (SUMMARY_TEXT, 1)
    assert isinstance(turn["ttftMs"], int)
    # 매 턴 방 전체를 다시 받지 않는다(만들 때 한 번뿐).
    assert run["server"].paths("GET", f"/chat-rooms/{ROOM_ID}") == []


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
    note.write_text("도희: 편집 담당")
    run["server"].turns = [_turn(), _turn()]
    assert _say(run, "안녕", "--set-note", str(note)) == 0
    capsys.readouterr()
    assert _say(run) == 0
    assert "[기억 노트]\n도희: 편집 담당" in capsys.readouterr().out


def test_shortcut_sends_prompt_and_id_but_logs_only_the_name(
    run: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    _create(run)
    capsys.readouterr()
    run["server"].turns = [_turn({"type": "token", "delta": "며칠 뒤"})]
    code = _main(run, "--room", ROOM_ID, "--server-log", str(run["server_log"]), "--shortcut", "며칠 뒤로")
    assert code == 0
    sent = run["server"].paths("POST", "/messages")[0][2]
    assert sent == {"content": "민준은 며칠을 건너뛴다(비공개 원문)", "shortcutId": SHORTCUT_ID}
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
    note.write_text("  도희: 편집 담당  \n")
    run["server"].turns = [_turn()]
    assert _say(run, "안녕", "--set-note", str(note)) == 0
    methods = [
        c[0] + " " + c[1].rsplit("/", 1)[-1] for c in run["server"].calls if "memory" in c[1] or "messages" in c[1]
    ]
    assert methods == ["PUT note", "GET memory", "POST messages"]
    update = _records(run["log"], "noteUpdate")[0]
    assert (update["note"], update["length"]) == ("도희: 편집 담당", 9)
    assert update["sha256"] == chat_play._sha("도희: 편집 담당")
    assert _records(run["log"], "turn")[0]["memory"]["noteSha"] == update["sha256"]
    assert "[기억 노트]\n도희: 편집 담당" in capsys.readouterr().out


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
    assert ending == {"id": ENDING_ID, "name": "다음 작품의 첫 장", "epilogue": "민준의 첫 장 [그림: 도희/기획 회의]"}


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
    assert _say(run) == 5
    assert chat_play.RATE_LIMIT_NOTICE in capsys.readouterr().out


def test_gemini_429_logged_after_the_previous_turn_stops_the_next_turn_before_sending(run: dict[str, Any]) -> None:
    _create(run)
    run["server"].turns = [_turn()]
    assert _say(run) == 0
    with run["server_log"].open("a") as f:
        f.write(f"WARNING 대화방 {ROOM_ID} 요약 접기 실패 (커서 x): 429 RESOURCE_EXHAUSTED\n")
    sent_before = len(run["server"].paths("POST", "/messages"))
    assert _say(run) == 5
    assert len(run["server"].paths("POST", "/messages")) == sent_before


def test_app_429_access_lines_and_other_rooms_do_not_count_as_gemini_429(run: dict[str, Any]) -> None:
    _create(run)
    with run["server_log"].open("a") as f:
        f.write(f'INFO: 127.0.0.1:1 - "POST /chat-rooms/{ROOM_ID}/messages HTTP/1.1" 429 Too Many Requests\n')
        f.write("WARNING 대화방 00000000-0000-4000-8000-000000000000 판정 실패: 429 RESOURCE_EXHAUSTED\n")
    hit, _ = chat_play.scan_gemini_429(run["server_log"], 0, ROOM_ID)
    assert hit is False


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


def test_milestone_first_reach_pauses_after_the_turn_without_saying_why(
    run: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    _create(run)
    capsys.readouterr()
    run["server"].turns = [
        _turn({"type": "statChange", "statId": STAT_DAYS, "newValue": 7}),
        _turn({"type": "statChange", "statId": STAT_DAYS, "newValue": 6}),
        _turn({"type": "statChange", "statId": STAT_DAYS, "newValue": 0}),
    ]
    assert _say(run) == 10
    assert capsys.readouterr().out.rstrip().splitlines()[-1] == chat_play.PAUSE_NOTICE
    assert _say(run) == 0  # 7 은 이미 도달
    assert _say(run) == 10  # 0 첫 도달
    assert [r["threshold"] for r in _records(run["snap"], "pause")] == [7.0, 0.0]
    assert all("trigger" not in r for r in _records(run["log"], "pause"))


def test_lost_turn_is_followed_by_a_rebase_before_the_next_turn(run: dict[str, Any]) -> None:
    _create(run)
    run["server"].turns = [_turn({"type": "error", "message": "생성 실패"}, done=False), _turn()]
    assert _say(run) == 0
    assert _records(run["log"], "turn")[0]["roomAfter"] is None
    assert _say(run) == 0
    rebase = _records(run["log"], "rebase")[0]
    assert rebase["reason"] == "유실 턴 뒤" and rebase["roomAfter"]["source"] == "refetch"
    assert _records(run["log"], "turn")[1]["roomAfter"]["turnCount"] == 1
