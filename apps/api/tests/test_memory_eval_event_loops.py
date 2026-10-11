"""하네스는 한 프로세스에서 `asyncio.run` 을 여러 번 부른다(프로브마다 복원·사용량 조회). 앱의 모듈 싱글턴(Redis 클라이언트·DB
엔진)은 처음 쓴 이벤트 루프에 묶여 두 번째 루프에서 "다른 루프에 붙은 Future" 로 죽는다 — 하네스 쪽은 호출마다 연결을 만들고
그 루프 안에서 닫아야 한다. 이 테스트는 그 연속 호출을 실제 격리 Redis 로 재현한다."""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from memory_eval.ledger import Ledger
from memory_eval.plants import Probe
from memory_eval.probe import BurstPacer


def test_clearing_room_keys_works_in_consecutive_event_loops() -> None:
    from memory_eval.checkpoint import clear_room_redis_keys

    room = uuid.uuid4()
    for _ in range(2):
        asyncio.run(clear_room_redis_keys(room))


def test_two_probes_in_a_row_restore_through_real_redis(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from memory_eval import checkpoint as checkpoint_mod
    from memory_eval import probe as probe_mod
    from memory_eval import server as server_mod

    room = uuid.uuid4()
    dumps = tmp_path / "dumps"
    fingerprint = {"turnCount": 50}
    checkpoint_mod.write_fingerprint(checkpoint_mod.fingerprint_path(dumps, 50, "s4"), fingerprint)

    async def clone(*_: Any, **__: Any) -> None:
        return None

    async def read_fp(*_: Any) -> dict[str, Any]:
        return dict(fingerprint)

    def start(overrides: dict[str, str], **kwargs: Any) -> Any:
        kwargs["log"].write_text("")
        return server_mod.ServerHandle(process=None, base="http://fake", log=kwargs["log"])  # type: ignore[arg-type]

    def driver(run: Any, base: str, folder: Path, *extra: str) -> int:
        if extra[0] == "--say":
            with (folder / "chat.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"kind": "turn", "reply": "응답"}) + "\n")
        return 0

    async def usage(*_: Any) -> list[dict[str, Any]]:
        return []

    # 복원은 실제 함수 — DB 복제·지문 읽기만 흉내 내고 Redis 키 지우기는 실제 격리 Redis 로 돈다.
    monkeypatch.setattr(checkpoint_mod, "clone_database", clone)
    monkeypatch.setattr(checkpoint_mod, "read_fingerprint", read_fp)
    monkeypatch.setattr(server_mod, "start", start)
    monkeypatch.setattr(server_mod, "stop", lambda _h: None)
    monkeypatch.setattr(probe_mod, "_driver", driver)
    monkeypatch.setattr(probe_mod, "_turn_usage", usage)
    run = probe_mod.ProbeRun(
        stage="s4",
        arm="baseline",
        room_id=room,
        run_dir=tmp_path,
        database_url="postgresql+asyncpg://x@localhost/lm_eval_work",
        cred_file=tmp_path / "cred",
        cookie_file=tmp_path / "cookie",
        port=8130,
        server_overrides={},
        allow_paid=False,
        opus_turn_usd=0.13,
        judgment_turn_usd=0.003,
        ledger=Ledger(tmp_path / "ledger.jsonl", cap_usd=30.0),
        pacer=BurstPacer(limit=9, window_seconds=60.0),
        checkpoint_label="s4",
    )
    for item in ("obj01", "obj03"):
        result = probe_mod.run_probe(run, Probe(item_id=item, checkpoint=50, turns=["질문"], kind="plant", split="dev"))
        assert result["status"] == "accept"
