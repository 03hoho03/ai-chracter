"""로컬 측정 서버(chat-lab)의 HTTP 계약과 가드.

앱은 httpx `ASGITransport` 로 부른다. 묶음은 측정 드라이버를 테스트 앱에 실제로 붙여 만든다(`driver_harness.drive_room`) —
손으로 쓴 사본은 기록 함수가 바뀌어도 그대로라 서버가 사본만 맞추게 된다. 손으로 쓰는 것은 실제 드라이버가 지금 만들지 않는
모양(옛 형식 로그)뿐이다. 응답은 라이브러리 함수가 같은 묶음에서 낸 모델과 견준다 — 서버가 결합·지표를 따로 계산하면 화면과
리플레이·원가 리포트의 숫자가 갈린다.

목록·상세만 받는 앱은 닿을 수 없는 로컬 DB 주소로 만든다. 그 요청들이 DB 에 접속하려 들면 그 자리에서 실패해 드러난다."""

import base64
import json
import os
import re
import shutil
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from redis.asyncio.connection import AbstractConnection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import chat_lab_server
from api.core.config import settings
from api.llm import dependencies
from api.llm.anthropic_api import AnthropicLLMClient
from api.llm.bedrock import BedrockLLMClient
from api.llm.gemini import GeminiLLMClient
from api.llm.routing import RoutingLLMClient
from api.llm.voyage import VoyageEmbeddingClient
from chat_lab import catalog, report
from chat_lab.app import LAB_WEB_ORIGINS, create_app
from chat_lab.bundles import CHAT_TURNS_NAME, DUMP_NAME, MANIFEST_NAME, SNAPSHOTS_NAME, discover_bundles
from chat_lab.chat_turns_file import export_text
from chat_lab.join import join_bundle
from chat_lab.report import list_entry, run_bundle, run_detail, run_metrics, turn_detail
from chat_lab.run_id import encode_run_id
from driver_harness import DRIVE_PERSONA_THEN, DrivenRoom, drive_room, says

# 로컬 주소라 가드는 통과하지만 아무것도 듣지 않는 포트 — 접속하려 들면 곧바로 실패한다.
UNREACHABLE_DB = "postgresql+asyncpg://lab:lab@127.0.0.1:1/chat_lab_unreachable"
BASE_URL = "http://127.0.0.1:8791"


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _dumped(model: Any) -> Any:
    return model.model_dump(mode="json", by_alias=True)


def _raw_id(text: str | bytes) -> str:
    data = text.encode() if isinstance(text, str) else text
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _strings(value: Any) -> set[str]:
    """응답 JSON 안의 문자열 값 전부."""
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(_strings(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_strings(v) for v in value)) if value else set()
    return set()


async def _run_root(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **drive: Any
) -> tuple[Path, DrivenRoom, Path]:
    """실제 런 하나를 `tmp_path / "root" / "runs" / "a"` 에 둔다. (런 루트, 돈 방, 묶음 폴더)."""
    root = tmp_path / "root"
    folder = root / "runs" / "a"
    driven = await drive_room(db_session, monkeypatch, tmp_path, export_dir=folder, **drive)
    return root, driven, folder


async def _short_root(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, DrivenRoom, Path]:
    return await _run_root(db_session, monkeypatch, tmp_path, script=says(2), failing_generations=(), stat_verdicts={})


def _write_legacy(folder: Path) -> None:
    """턴 줄에 방 id 가 없는 옛 형식 로그."""
    folder.mkdir(parents=True)
    room = "00000000-0000-0000-0000-00000000aaaa"
    lines = [
        {"kind": "meta", "roomId": room, "storyName": "옛 이야기"},
        {"kind": "turn", "clientTurn": 1, "userText": "안녕", "reply": "응답", "intent": "인사"},
    ]
    (folder / "turns.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")


async def test_endpoints_answer_with_the_library_models_for_a_real_run(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """목록·상세·턴·지표는 라이브러리가 같은 묶음에서 낸 모델 그대로여야 한다(키는 카멜 표기). 유실 턴 재시도가 있는 기본
    대본으로 돌려 턴 7 에 시도가 둘인 턴 상세를 본다. 없는 턴과, 모양은 맞지만 가리키는 묶음이 없는 id 는 404 다."""
    root, _, folder = await _run_root(db_session, monkeypatch, tmp_path)
    [bundle] = discover_bundles(root)
    joined = join_bundle(bundle)
    app = create_app(root=root, database_url=UNREACHABLE_DB)

    async with _client(app) as client:
        health = await client.get("/health")
        listing = await client.get("/runs")
        detail = await client.get(f"/runs/{bundle.run_id}")
        turn = await client.get(f"/runs/{bundle.run_id}/turns/7")
        metrics = await client.get(f"/runs/{bundle.run_id}/metrics")
        missing_turn = await client.get(f"/runs/{bundle.run_id}/turns/99")
        no_bundle = await client.get(f"/runs/{encode_run_id(root, folder / 'other.jsonl')}")

    assert (health.status_code, health.json()) == (200, {"status": "ok"})
    assert listing.status_code == 200
    body = listing.json()
    assert body["items"] == [_dumped(list_entry(bundle))]
    assert isinstance(body["discoveredAt"], str)
    assert body["items"][0]["runId"] == bundle.run_id
    assert body["items"][0]["turnCount"] == 12
    assert (detail.status_code, detail.json()) == (200, _dumped(run_detail(joined)))
    assert (turn.status_code, turn.json()) == (200, _dumped(turn_detail(joined, 7)))
    assert len(turn.json()["attempts"]) == 2
    assert (metrics.status_code, metrics.json()) == (200, _dumped(run_metrics(joined)))
    assert (missing_turn.status_code, no_bundle.status_code) == (404, 404)
    assert [missing_turn.json()["reason"], no_bundle.json()["reason"]] == ["notFound", "notFound"]


async def test_the_whole_bundle_drops_prompts_instructions_and_snapshot_text_only_without_raw(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """정적 HTML 은 통째 응답 하나만 주입하므로 모든 턴 상세가 실려야 한다. 원문 없는 묶음은 이 방 덤프 줄의 프롬프트·지시문과
    기억 스냅숏의 노트·요약 본문이 어디에도 없어야 하고(키도 남지 않는다), 원문 묶음에는 그것들이 하나도 빠짐없이 있어야 한다
    — 한쪽만 보면 "아무것도 싣지 않는" 구현과 "아무것도 빼지 않는" 구현이 각각 통과한다. 상세의 방 스냅숏(단축어 프롬프트 전문·
    대화 프로필 설명)도 같은 짝으로 본다 — 원문 묶음에는 있고 원문 없는 묶음에는 비어 있다. 상세의 나머지와 지표는 두 묶음이 같다."""
    root, driven, _ = await _run_root(db_session, monkeypatch, tmp_path)
    [bundle] = discover_bundles(root)
    joined = join_bundle(bundle)
    app = create_app(root=root, database_url=UNREACHABLE_DB)

    async with _client(app) as client:
        raw = await client.get(f"/runs/{bundle.run_id}/bundle", params={"raw": "true"})
        bare = await client.get(f"/runs/{bundle.run_id}/bundle", params={"raw": "false"})

    assert (raw.status_code, bare.status_code) == (200, 200)
    assert raw.json() == _dumped(run_bundle(joined, raw=True))
    assert bare.json() == _dumped(run_bundle(joined, raw=False))
    assert (raw.json()["raw"], bare.json()["raw"]) == (True, False)
    assert [t["turn"] for t in raw.json()["turns"]] == [t.number for t in joined.turns] == list(range(1, 13))
    raw_static = raw.json()["detail"]["roomStatic"]
    assert raw_static is not None
    assert raw_static["shortcuts"]
    assert all(isinstance(s["prompt"], str) and s["prompt"] for s in raw_static["shortcuts"])
    assert raw_static["persona"]["description"] == DRIVE_PERSONA_THEN
    assert bare.json()["detail"]["roomStatic"] is None
    assert bare.json()["detail"] == {**raw.json()["detail"], "roomStatic": None}
    assert bare.json()["metrics"] == raw.json()["metrics"]

    room_dump = [r for r in _jsonl(driven.dump) if r.get("roomId") == str(driven.room_id)]
    instructions = {r["systemInstruction"] for r in room_dump if r.get("systemInstruction")}
    assert instructions
    assert {r["prompt"] for r in room_dump} | instructions <= _strings(raw.json())
    shown = [t["memorySnapshot"] for t in raw.json()["turns"] if t["memorySnapshot"] is not None]
    notes = {s["note"] for s in shown if s["note"]}
    summaries = {s["summary"] for s in shown if s["summary"]}
    assert notes and summaries
    originals = {r["prompt"] for r in room_dump} | instructions | notes | summaries
    assert originals.isdisjoint(_strings(bare.json()))
    for turn in bare.json()["turns"]:
        dumps = [a["generationDump"] for a in turn["attempts"] if a["generationDump"] is not None]
        dumps += turn["earlierGenerationDumps"] + turn["judgmentDumps"] + [b["record"] for b in turn["backgroundDumps"]]
        assert all({"prompt", "systemInstruction"}.isdisjoint(d) for d in dumps)
        assert turn["memorySnapshot"] is None or {"note", "summary"}.isdisjoint(turn["memorySnapshot"])


async def test_an_unsupported_bundle_is_listed_but_every_detail_answers_unsupported(tmp_path: Path) -> None:
    """옛 형식 묶음은 턴 줄에 방 id 가 없어 열지 않는다. 목록에는 "지원 안 함"으로 보이고, 상세·턴·지표·통째 묶음은 모두 같은
    상태 코드(422)로 지원 안 함을 알린다 — 엔드포인트마다 다르면 화면이 같은 사정을 다르게 보인다."""
    root = tmp_path / "root"
    _write_legacy(root / "story-guide" / "r1")
    [bundle] = discover_bundles(root)
    app = create_app(root=root, database_url=UNREACHABLE_DB)

    async with _client(app) as client:
        listing = await client.get("/runs")
        answers = [
            await client.get(f"/runs/{bundle.run_id}"),
            await client.get(f"/runs/{bundle.run_id}/turns/1"),
            await client.get(f"/runs/{bundle.run_id}/metrics"),
            await client.get(f"/runs/{bundle.run_id}/bundle", params={"raw": "false"}),
        ]

    [item] = listing.json()["items"]
    assert (item["supported"], item["format"]) == (False, "legacy")
    assert [(answer.status_code, answer.json()["reason"]) for answer in answers] == [(422, "unsupported")] * 4


async def test_only_this_servers_refusals_carry_a_reason_and_request_validation_keeps_the_framework_shape(
    tmp_path: Path,
) -> None:
    """422 는 두 가지가 온다 — 요청 모양이 틀린 것(FastAPI 검증, `detail` 이 목록이고 `reason` 이 없다)과 이 서버가 그 묶음을
    거부한 것(`LabError`). 웹은 `reason` 이 있는지로 둘을 가른다 — 앞의 것은 웹의 버그이고 뒤의 것은 사용자에게 보일 사정이다."""
    root = tmp_path / "root"
    _write_legacy(root / "story-guide" / "r1")
    [bundle] = discover_bundles(root)
    app = create_app(root=root, database_url=None)

    async with _client(app) as client:
        refused = await client.get(f"/runs/{bundle.run_id}")
        malformed = [
            await client.get(f"/runs/{bundle.run_id}/turns/first"),
            await client.get(f"/runs/{bundle.run_id}/bundle"),
            await client.post(f"/runs/{bundle.run_id}/export-turns", json={"force": "maybe"}),
            await client.post(f"/runs/{bundle.run_id}/export-turns", json={}),
        ]

    assert refused.status_code == 422
    assert set(refused.json()) == {"detail", "reason"}
    assert (refused.json()["reason"], isinstance(refused.json()["detail"], str)) == ("unsupported", True)
    assert [answer.status_code for answer in malformed] == [422] * 4
    assert all("reason" not in answer.json() and isinstance(answer.json()["detail"], list) for answer in malformed)


async def test_a_forged_host_header_is_refused_and_loopback_names_with_a_port_pass(tmp_path: Path) -> None:
    """서버는 loopback 에만 묶지만, 악성 페이지가 자기 도메인을 127.0.0.1 로 다시 풀게 하면(DNS rebinding) 브라우저는 그
    도메인 이름을 Host 로 보낸다. Host 가 허용 목록 밖이면 라우팅 전에 거부해야 한다(쓰기 요청도). 브라우저가 포트를 붙여
    보내는 정상 Host 는 통과해야 한다."""
    app = create_app(root=tmp_path, database_url=UNREACHABLE_DB)

    async with _client(app) as client:
        forged_get = await client.get("/health", headers={"Host": "evil.example"})
        forged_post = await client.post(
            "/runs/x/export-turns", json={"force": False}, headers={"Host": "evil.example:8791"}
        )
        allowed = [await client.get("/health", headers={"Host": host}) for host in ("127.0.0.1:8791", "localhost:8791")]

    assert (forged_get.status_code, forged_post.status_code) == (400, 400)
    assert [answer.status_code for answer in allowed] == [200, 200]


async def test_a_post_that_is_not_json_is_refused_before_routing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """브라우저는 폼·`text/plain` POST 를 사전 요청 없이 다른 사이트에서도 보낸다(CSRF). JSON 본문만 받아야 그런 요청이 CORS
    사전 요청을 거치게 된다. 쓰기 엔드포인트든 없는 경로든 POST 이면 라우팅 전에 415 이고 파일은 생기지 않는다. 문자 집합을
    붙인 JSON 은 통과한다(DB 를 주지 않은 앱이라 그다음 거부는 503)."""
    root, _, folder = await _short_root(db_session, monkeypatch, tmp_path)
    [bundle] = discover_bundles(root)
    app = create_app(root=root, database_url=None)
    path = f"/runs/{bundle.run_id}/export-turns"

    async with _client(app) as client:
        refused = [
            await client.post(path, data={"force": "true"}),
            await client.post(path, content=b'{"force": true}', headers={"Content-Type": "text/plain"}),
            await client.post(path, files={"force": ("f", b"true")}),
            await client.post(path, content=b'{"force": true}'),
            await client.post("/no-such-route", content=b"x", headers={"Content-Type": "text/plain"}),
        ]
        passed = await client.post(
            path, content=b'{"force": true}', headers={"Content-Type": "application/json; charset=utf-8"}
        )

    assert [(answer.status_code, answer.json()["reason"]) for answer in refused] == [(415, "notJson")] * 5
    assert (passed.status_code, passed.json()["reason"]) == (503, "dbUnavailable")
    assert not (folder / CHAT_TURNS_NAME).exists()


async def test_cors_answers_only_the_lab_web_origin(tmp_path: Path) -> None:
    """측정 웹 dev 서버의 오리진만 응답을 읽을 수 있어야 한다. 다른 오리진의 사전 요청은 거부되고 어느 응답에도 허용 헤더가
    붙지 않는다."""
    app = create_app(root=tmp_path, database_url=UNREACHABLE_DB)
    preflight = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}

    async with _client(app) as client:
        allowed = [
            await client.options("/runs/x/export-turns", headers={**preflight, "Origin": origin})
            for origin in LAB_WEB_ORIGINS
        ]
        allowed_get = await client.get("/health", headers={"Origin": LAB_WEB_ORIGINS[0]})
        other = await client.options("/runs/x/export-turns", headers={**preflight, "Origin": "http://evil.example"})
        other_get = await client.get("/health", headers={"Origin": "http://evil.example"})

    assert sorted(LAB_WEB_ORIGINS) == ["http://127.0.0.1:5291", "http://localhost:5291"]
    assert [a.headers.get("access-control-allow-origin") for a in allowed] == list(LAB_WEB_ORIGINS)
    assert allowed_get.headers.get("access-control-allow-origin") == LAB_WEB_ORIGINS[0]
    assert other.status_code == 400
    assert "access-control-allow-origin" not in other.headers
    assert "access-control-allow-origin" not in other_get.headers


async def test_run_ids_that_leave_the_root_or_pass_through_a_link_are_not_found(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """id 는 누구나 만들어 보낼 수 있다. `..`·절대 경로·루트 안의 링크(루트 안을 가리키든 밖을 가리키든)·경로 글자가 아닌 값은
    모두 없는 묶음과 같은 404 여야 하고, 쓰기 요청도 그 경로에 아무것도 쓰지 않는다 — 어느 모양이 거부됐는지 가르는 응답은
    알려 줄 이유가 없다."""
    root, _, folder = await _short_root(db_session, monkeypatch, tmp_path)
    outside = tmp_path / "outside"
    shutil.copytree(folder, outside)
    (root / "inner-link").symlink_to(folder)
    (root / "outer-link").symlink_to(outside)
    forged = [
        _raw_id("../outside/chat.jsonl"),
        _raw_id("runs/../../outside/chat.jsonl"),
        _raw_id(str((outside / "chat.jsonl").resolve())),
        _raw_id("inner-link/chat.jsonl"),
        _raw_id("outer-link/chat.jsonl"),
        _raw_id(b"\xff\xfe"),
    ]
    app = create_app(root=root, database_url=UNREACHABLE_DB)

    async with _client(app) as client:
        reads = [await client.get(f"/runs/{run_id}") for run_id in forged]
        writes = [await client.post(f"/runs/{run_id}/export-turns", json={"force": True}) for run_id in forged]

    assert [(answer.status_code, answer.json()["reason"]) for answer in reads + writes] == [(404, "notFound")] * (
        2 * len(forged)
    )
    assert not (outside / CHAT_TURNS_NAME).exists()
    assert not (folder / CHAT_TURNS_NAME).exists()


def test_the_app_refuses_a_database_that_is_not_local(tmp_path: Path) -> None:
    """측정 서버는 로컬 DB 만 읽는다. 운영 DB 호스트(compose 서비스명)나 바깥 주소를 받으면 앱을 만들지 않는다. 로컬 주소는
    받되 만드는 동안 접속하지 않는다(닿을 수 없는 주소로도 만들어진다)."""
    for url in (
        "postgresql+asyncpg://u:p@postgres:5432/ai_character_chat",
        "postgresql+asyncpg://u:p@db.example.com/x",
    ):
        with pytest.raises(SystemExit):
            create_app(root=tmp_path, database_url=url)
    assert isinstance(create_app(root=tmp_path, database_url=UNREACHABLE_DB), FastAPI)


def test_the_server_entry_binds_loopback_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """바인드 주소는 127.0.0.1 고정이고 호스트를 바꾸는 인자는 없다 — 같은 망의 다른 기기가 덤프 원문을 읽지 못하게. 로컬이
    아닌 DB 를 주면 서버를 띄우지 않는다."""
    calls: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))

    assert chat_lab_server.main(["--port", "8799", "--root", str(tmp_path), "--database-url", UNREACHABLE_DB]) == 0
    with pytest.raises(SystemExit):
        chat_lab_server.main(["--host", "0.0.0.0", "--root", str(tmp_path), "--database-url", UNREACHABLE_DB])
    with pytest.raises(SystemExit):
        chat_lab_server.main(["--root", str(tmp_path), "--database-url", "postgresql+asyncpg://u:p@postgres/x"])

    assert [(type(app), kwargs) for app, kwargs in calls] == [(FastAPI, {"host": "127.0.0.1", "port": 8799})]


async def test_reading_endpoints_build_no_llm_client_and_open_no_redis_or_database_connection(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """측정 서버는 기록 파일만 읽는다. 목록·상세·턴·지표·통째 묶음을 부르는 동안 LLM 클라이언트를 하나도 만들지 않고, Redis
    에 접속하지 않으며, DB 엔진을 만들지 않는다(DB 는 턴 기록 내보내기 때만 연다). 감시는 런을 만든 뒤에 건다 — 런을 만드는
    테스트 앱은 Redis·가짜 LLM 을 쓴다."""
    root, _, _ = await _run_root(db_session, monkeypatch, tmp_path)
    [bundle] = discover_bundles(root)
    seen: Counter[str] = Counter()

    def counting_init(name: str, original: Callable[..., None]) -> Callable[..., None]:
        def init(self: Any, *args: Any, **kwargs: Any) -> None:
            seen[name] += 1
            original(self, *args, **kwargs)

        return init

    for cls in (
        GeminiLLMClient,
        RoutingLLMClient,
        AnthropicLLMClient,
        BedrockLLMClient,
        VoyageEmbeddingClient,
        AsyncEngine,
    ):
        monkeypatch.setattr(cls, "__init__", counting_init(cls.__name__, cls.__init__))
    original_get = dependencies.get_llm_client

    def counting_get() -> Any:
        seen["get_llm_client"] += 1
        return original_get()

    monkeypatch.setattr(dependencies, "get_llm_client", counting_get)

    async def refuse_connect(self: AbstractConnection, *args: Any, **kwargs: Any) -> None:
        seen["redis"] += 1
        raise ConnectionError("측정 서버가 Redis 에 접속하려 했다")

    monkeypatch.setattr(AbstractConnection, "connect_check_health", refuse_connect)

    app = create_app(root=root, database_url=UNREACHABLE_DB)
    async with _client(app) as client:
        answers = [
            await client.get("/health"),
            await client.get("/runs"),
            await client.get("/runs", params={"refresh": "true"}),
            await client.get(f"/runs/{bundle.run_id}"),
            await client.get(f"/runs/{bundle.run_id}/turns/7"),
            await client.get(f"/runs/{bundle.run_id}/metrics"),
            await client.get(f"/runs/{bundle.run_id}/bundle", params={"raw": "true"}),
            await client.get(f"/runs/{bundle.run_id}/bundle", params={"raw": "false"}),
        ]

    assert [answer.status_code for answer in answers] == [200] * len(answers)
    assert seen == Counter()


async def test_the_listing_rejoins_only_the_bundle_whose_files_changed(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """루트 탐색은 실데이터에서 수십 초라 결과를 들고 있고, 다시 훑기 전까지는 묶음마다 파일 서명(수정 시각·크기)이 같으면
    결합 결과를 다시 쓴다. 파일이 바뀐 묶음만 다시 잇고, 그 폴더에 턴 기록 파일이 새로 생기면 다시 훑지 않아도 짝으로 잡힌다
    (내보내기 명령을 서버 밖에서 돌린 경우). 상세도 같은 서명이면 다시 잇지 않는다."""
    root, driven, folder = await _short_root(db_session, monkeypatch, tmp_path)
    twin = root / "runs" / "b"
    shutil.copytree(folder, twin)
    listing_joins: list[Path] = []
    detail_joins: list[Path] = []

    def spy(seen: list[Path]) -> Callable[..., Any]:
        def join(bundle: Any) -> Any:
            seen.append(bundle.log.parent)
            return join_bundle(bundle)

        return join

    monkeypatch.setattr(report, "join_bundle", spy(listing_joins))
    monkeypatch.setattr(catalog, "join_bundle", spy(detail_joins))
    a, b = discover_bundles(root)
    app = create_app(root=root, database_url=UNREACHABLE_DB)

    async with _client(app) as client:
        first = (await client.get("/runs")).json()
        assert sorted(listing_joins) == sorted([folder.resolve(), twin.resolve()])
        second = (await client.get("/runs")).json()
        assert len(listing_joins) == 2
        assert second["items"] == first["items"]

        with (twin / DUMP_NAME).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"roomId": "other-room", "turn": 1, "kind": "generation", "prompt": "p"}) + "\n")
        (await client.get("/runs")).json()
        assert listing_joins[2:] == [twin.resolve()]

        await client.get(f"/runs/{a.run_id}")
        await client.get(f"/runs/{a.run_id}/metrics")
        await client.get(f"/runs/{a.run_id}/turns/1")
        assert detail_joins == [folder.resolve()]
        with (folder / SNAPSHOTS_NAME).open("a", encoding="utf-8") as handle:
            handle.write("\n")
        await client.get(f"/runs/{a.run_id}")
        assert detail_joins == [folder.resolve(), folder.resolve()]

        text = export_text(
            room_id=str(driven.room_id), exported_at=datetime(2026, 10, 30, 12, 0, tzinfo=UTC), stat_defs=[], rows=[]
        )
        (twin / CHAT_TURNS_NAME).write_text(text, encoding="utf-8")
        after_export = (await client.get("/runs")).json()

    items = {item["runId"]: item for item in after_export["items"]}
    assert (items[a.run_id]["hasChatTurns"], items[b.run_id]["hasChatTurns"]) == (False, True)
    assert listing_joins[3:] == [folder.resolve(), twin.resolve()]


async def test_a_refresh_drops_held_results_so_a_new_bundle_of_the_same_room_marks_room_sharing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """같은 방을 쓰는 묶음이 새로 생기면, 매니페스트로 같은 폴더 밖 짝을 쓰는 묶음에 "방 공유" 주의가 붙어야 한다(그 짝 파일에
    다른 시도의 줄이 섞였을 수 있다). 묶음 수는 그 묶음의 파일 서명에 없어 서명이 같다고 들고 있던 결과를 다시 쓰면 주의가
    빠진다 — 다시 훑기는 목록 항목과 상세 결합을 모두 다시 만들어야 한다. 다시 훑기 전에는 새 묶음이 보이지 않는다."""
    root, _, folder = await _short_root(db_session, monkeypatch, tmp_path)
    dumps = root / "dumps"
    dumps.mkdir()
    (folder / DUMP_NAME).replace(dumps / DUMP_NAME)
    (folder / MANIFEST_NAME).write_text(json.dumps({"dump": f"../../dumps/{DUMP_NAME}"}), encoding="utf-8")
    [a] = discover_bundles(root)
    app = create_app(root=root, database_url=UNREACHABLE_DB)

    async with _client(app) as client:
        [before] = (await client.get("/runs")).json()["items"]
        detail_before = (await client.get(f"/runs/{a.run_id}")).json()
        other = root / "runs" / "b"
        other.mkdir()
        shutil.copy2(folder / "chat.jsonl", other / "chat.jsonl")
        unrefreshed = (await client.get("/runs")).json()["items"]
        refreshed = {
            item["runId"]: item for item in (await client.get("/runs", params={"refresh": "true"})).json()["items"]
        }
        detail_after = (await client.get(f"/runs/{a.run_id}")).json()

    assert before["hasDump"] is True
    assert "roomShared" not in {c["kind"] for c in detail_before["cautions"]}
    assert [item["runId"] for item in unrefreshed] == [a.run_id]
    assert len(refreshed) == 2
    assert refreshed[a.run_id]["cautionCount"] == before["cautionCount"] + 1
    assert "roomShared" in {c["kind"] for c in detail_after["cautions"]}


def test_the_openapi_dump_is_byte_stable_and_carries_no_settings_or_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CI 는 같은 커밋에서 스키마를 다시 떨궈 커밋된 파일과 견준다. 러너에는 `.env` 가 없으므로 설정값(DB·Redis 주소)이나
    이 머신의 경로가 스키마에 들어가면 바이트가 갈린다. 떨구기는 가드·DB·서버 기동 전에 끝나야 한다(러너에는 기본 DB 가
    없다) — 서버 띄우기와 DB 가드가 불리면 실패하게 해 둔다. 런 루트가 달라도 스키마는 같다."""

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("스키마 떨구기가 서버나 DB 가드를 불렀다")

    monkeypatch.setattr(uvicorn, "run", refuse)
    monkeypatch.setattr("chat_lab.app.ensure_local_database", refuse)
    output = tmp_path / "chat-lab" / "openapi.json"
    monkeypatch.setattr(chat_lab_server, "OPENAPI_PATH", output)

    first = chat_lab_server.openapi_text()
    assert chat_lab_server.main(["--dump-openapi"]) == 0
    assert output.read_text(encoding="utf-8") == first == chat_lab_server.openapi_text()
    assert first.endswith("}\n")
    assert json.loads(first)["info"]["title"] == "chat-lab"
    assert create_app(root=tmp_path, database_url=None).openapi() == json.loads(first)
    for secret in {os.environ["DATABASE_URL"], settings.database_url, settings.redis_url, str(tmp_path)}:
        assert secret not in first
    assert str(Path(chat_lab_server.__file__).resolve().parent) not in first
    spec = json.loads(first)
    refs = {ref.removeprefix("#/components/schemas/") for ref in re.findall(r'"\$ref": "([^"]+)"', first)}
    assert refs <= set(spec["components"]["schemas"])
    statuses = {
        path: {method: sorted(op["responses"]) for method, op in ops.items()} for path, ops in spec["paths"].items()
    }
    read = ["200", "404", "422"]
    assert statuses["/runs/{runId}"] == statuses["/runs/{runId}/metrics"] == {"get": read}
    assert statuses["/runs/{runId}/bundle"] == statuses["/runs/{runId}/turns/{clientTurn}"] == {"get": read}
    assert statuses["/runs/{runId}/export-turns"] == {"post": ["200", "403", "404", "409", "415", "422", "503"]}
    unprocessable = spec["paths"]["/runs/{runId}/export-turns"]["post"]["responses"]["422"]
    assert {item["$ref"] for item in unprocessable["content"]["application/json"]["schema"]["anyOf"]} == {
        "#/components/schemas/LabError",
        "#/components/schemas/HTTPValidationError",
    }
    paths = spec["paths"]
    assert sorted(paths) == [
        "/health",
        "/runs",
        "/runs/{runId}",
        "/runs/{runId}/bundle",
        "/runs/{runId}/export-turns",
        "/runs/{runId}/metrics",
        "/runs/{runId}/turns/{clientTurn}",
    ]
