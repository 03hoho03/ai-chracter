"""런 루트를 훑어 묶음(드라이버 로그 하나와 그 짝 파일)을 찾는 규칙.

드라이버 로그·스냅숏·덤프는 측정 드라이버를 테스트 앱에 실제로 붙여 만든다(`driver_harness.drive_room`) — 손으로 만든
사본은 기록 함수가 바뀌어도 그대로라 탐색이 사본만 맞추게 된다. 손으로 쓰는 것은 실제 드라이버가 지금 만들지 않는
모양뿐이다: 매니페스트, 같은 방을 쓰는 여러 묶음의 배치, 옛 형식 로그, 이름이 덤프가 아닌 파일의 `generation` 줄, 기록
중에 잘린 마지막 줄, 칸 타입이 깨진 줄."""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from chat_lab.bundles import (
    CHAT_TURNS_NAME,
    DUMP_NAME,
    MANIFEST_NAME,
    SNAPSHOTS_NAME,
    Bundle,
    discover_bundles,
    find_bundle,
)
from chat_lab.chat_turns_file import export_text
from chat_lab.join import UnsupportedBundleError, join_bundle
from chat_lab.report import list_entry, run_list_item
from driver_harness import DrivenRoom, drive_room, says


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _copy(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def _write_manifest(folder: Path, manifest: dict[str, str]) -> None:
    (folder / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")


def _by_folder(bundles: list[Bundle], root: Path) -> dict[str, Bundle]:
    return {bundle.log.parent.relative_to(root.resolve()).as_posix(): bundle for bundle in bundles}


async def _short_run(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> DrivenRoom:
    """두 턴짜리 실제 런. 드라이버 작업 파일은 `tmp_path` 에 남고, 테스트는 그 산출물을 `tmp_path / "root"` 아래에 배치해 훑는다."""
    return await drive_room(db_session, monkeypatch, tmp_path, script=says(2), failing_generations=(), stat_verdicts={})


async def test_a_real_run_is_found_with_its_same_folder_pair_files_and_turns_jsonl_is_not_a_pair(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """드라이버가 쓴 세 파일과 내보낸 턴 기록이 한 폴더에 있으면 매니페스트 없이 묶여야 한다. 옛 측정은 드라이버 로그를
    `turns.jsonl` 로 썼으므로, 그 이름을 턴 기록 짝으로 읽으면 드라이버 로그를 턴 기록으로 열게 된다 — 그 파일은 그 자체로
    묶음이어야 하고 어느 묶음의 짝도 아니어야 한다."""
    driven = await _short_run(db_session, monkeypatch, tmp_path)
    root = tmp_path / "root"
    run = root / "run"
    for source, name in ((driven.log, "chat.jsonl"), (driven.snapshot_log, SNAPSHOTS_NAME), (driven.dump, DUMP_NAME)):
        _copy(source, run / name)
    (run / CHAT_TURNS_NAME).write_text(
        export_text(room_id=str(driven.room_id), exported_at=datetime.now(UTC), stat_defs=[], rows=[]),
        encoding="utf-8",
    )
    _copy(driven.log, root / "story-guide" / "turns.jsonl")

    bundles = discover_bundles(root)
    found = _by_folder(bundles, root)

    assert sorted(found) == ["run", "story-guide"]
    bundle = found["run"]
    assert (bundle.format, bundle.supported, bundle.room_id) == ("current", True, str(driven.room_id))
    assert (bundle.snapshots, bundle.dump, bundle.chat_turns) == (
        (run / SNAPSHOTS_NAME).resolve(),
        (run / DUMP_NAME).resolve(),
        (run / CHAT_TURNS_NAME).resolve(),
    )
    assert bundle.group is None and bundle.cautions == []
    assert find_bundle(bundles, root, bundle.run_id) is bundle
    named_turns = found["story-guide"]
    assert named_turns.log.name == "turns.jsonl" and named_turns.chat_turns is None and named_turns.dump is None


async def test_manifest_pairs_files_outside_the_folder_and_only_then_flags_a_shared_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """같은 방을 여러 묶음이 쓰면(체크포인트 복원·가지치기 측정) 조상 폴더 덤프를 방 id 로 거를 때 다른 시도의 줄이 섞인다.
    그래서 같은 폴더 밖 짝은 매니페스트가 가리킬 때만 쓰고, 그때만 "방 공유" 주의를 단다 — 같은 폴더 짝만 쓰는 정상
    묶음에까지 달면 목록의 주의가 아무것도 가르지 못한다. 루트 밖·절대 경로를 가리키는 매니페스트 항목은 버리고 주의로
    남긴다. 시도 폴더(`probes`) 아래 묶음은 그 폴더까지의 경로를 묶음 키로 받는다."""
    driven = await _short_run(db_session, monkeypatch, tmp_path)
    root = tmp_path / "root"
    _copy(driven.dump, root / "dumps" / DUMP_NAME)

    _copy(driven.log, root / "a" / "chat.jsonl")
    _copy(driven.snapshot_log, root / "a" / "snapshots.jsonl")
    _write_manifest(root / "a", {"snapshots": "snapshots.jsonl", "dump": "../dumps/prompt-dump.jsonl"})

    for name, source in (("chat.jsonl", driven.log), (SNAPSHOTS_NAME, driven.snapshot_log), (DUMP_NAME, driven.dump)):
        _copy(source, root / "b" / name)
        _copy(source, root / "x" / "probes" / "p1" / "attempt1" / name)

    _copy(driven.log, root / "c" / "chat.jsonl")
    _copy(driven.dump, tmp_path / "outside.jsonl")
    _write_manifest(root / "c", {"dump": "../../outside.jsonl", "snapshots": str(driven.snapshot_log)})

    found = _by_folder(discover_bundles(root), root)

    assert sorted(found) == ["a", "b", "c", "x/probes/p1/attempt1"]
    assert {bundle.room_bundle_count for bundle in found.values()} == {4}
    a = found["a"]
    assert (a.snapshots, a.dump) == ((root / "a" / "snapshots.jsonl").resolve(), (root / "dumps" / DUMP_NAME).resolve())
    assert [caution.kind for caution in a.cautions] == ["roomShared"]
    assert found["b"].cautions == [] and found["b"].group is None
    assert found["x/probes/p1/attempt1"].group == "x/probes"
    c = found["c"]
    assert (c.dump, c.snapshots) == (None, None)
    assert [caution.kind for caution in c.cautions] == ["manifest", "manifest"]

    joined = join_bundle(a)
    assert joined.mismatches == []
    assert [turn.selected.generation_dump is not None for turn in joined.turns] == [True, True]


def test_legacy_driver_log_is_listed_as_unsupported_and_never_joined(tmp_path: Path) -> None:
    """턴 줄에 방 id 가 없는 옛 형식은 리플레이 규칙(방 id 로 줄을 거른다)을 거치면 턴이 0개가 된다. 조용히 빈 묶음으로
    열지 않고 목록에 "지원 안 함"으로만 보인다."""
    folder = tmp_path / "story-guide" / "r1"
    folder.mkdir(parents=True)
    room = "00000000-0000-0000-0000-00000000aaaa"
    lines = [
        {"kind": "meta", "roomId": room, "storyName": "옛 이야기"},
        {"kind": "turn", "clientTurn": 1, "userText": "안녕", "reply": "응답", "intent": "인사"},
    ]
    (folder / "turns.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")

    [bundle] = discover_bundles(tmp_path)

    assert (bundle.format, bundle.supported, bundle.room_id) == ("legacy", False, room)
    with pytest.raises(UnsupportedBundleError):
        join_bundle(bundle)
    item = run_list_item(bundle, None)
    assert (item.supported, item.format, item.turn_count, item.mismatch_count) == (False, "legacy", None, None)


async def test_a_trace_file_with_generation_lines_is_not_read_as_a_dump(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """옛 계측 `trace.jsonl` 에도 kind `generation` 줄이 있다(프롬프트는 없고 글자 수만). 줄의 kind 로 덤프를 고르면 그 파일을
    덤프로 읽어 "덤프가 있는데 프롬프트가 비었다"로 보인다. 이름이 기본 이름이 아니면 짝으로 고르지 않고, 매니페스트가
    가리켜도 방 id·프롬프트가 있는 줄만 덤프 줄로 친다."""
    driven = await _short_run(db_session, monkeypatch, tmp_path)
    root = tmp_path / "root"
    trace = {"kind": "generation", "roomId": str(driven.room_id), "turn": 1, "ok": True, "promptChars": 10}
    for folder in ("plain", "manifest"):
        _copy(driven.log, root / folder / "chat.jsonl")
        (root / folder / "trace.jsonl").write_text(json.dumps(trace) + "\n", encoding="utf-8")
    _write_manifest(root / "manifest", {"dump": "trace.jsonl"})

    found = _by_folder(discover_bundles(root), root)

    assert found["plain"].dump is None
    joined = join_bundle(found["manifest"])
    assert not joined.has_dump
    assert [turn.selected.generation_dump for turn in joined.turns] == [None, None]
    assert joined.mismatches == []
    assert [caution.kind for caution in joined.cautions] == ["notDumpLine"]


async def test_a_dump_cut_inside_a_character_while_the_server_writes_keeps_every_complete_line(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """측정 중인 서버가 덤프를 쓰는 동안 열면 마지막 줄이 잘려 있고, 한글은 세 바이트라 글자 가운데서도 잘린다. 파일을 통째로
    디코드하면 그 한 바이트 때문에 묶음 전체가 열리지 않아 진행 중인 런을 볼 수 없으므로, 잘린 마지막 줄만 버리고 주의로
    남긴다. 가운데 줄이 깨진 것은 잘림이 아니라 읽지 못한 줄이라 다른 주의로 남기고, 나머지 줄은 그대로 읽는다."""
    driven = await _short_run(db_session, monkeypatch, tmp_path)
    run = tmp_path / "root" / "run"
    _copy(driven.log, run / "chat.jsonl")
    _copy(driven.snapshot_log, run / SNAPSHOTS_NAME)
    complete = driven.dump.read_bytes()
    last = complete.split(b"\n")[-2]
    # 세 바이트 글자의 첫 바이트 바로 뒤에서 자른다 — 문자열로 자르면 글자 경계에서만 잘려 디코드 실패를 밟지 않는다.
    cut = next(index for index, byte in enumerate(last) if byte >= 0xE0) + 1
    assert last[cut] & 0xC0 == 0x80
    first, rest = complete.split(b"\n", 1)
    (run / DUMP_NAME).write_bytes(first + b"\n" + b"\xff\xfe not json\n" + rest + last[:cut])

    [bundle] = discover_bundles(tmp_path / "root")
    joined = join_bundle(bundle)

    assert joined.mismatches == []
    assert [turn.selected.generation_dump is not None for turn in joined.turns] == [True, True]
    assert len(joined.dump_records) == len(_jsonl(driven.dump))
    assert [caution.kind for caution in joined.cautions] == ["unreadableLine", "incompleteLine"]


async def test_a_bundle_alone_on_its_room_pairs_outside_its_folder_without_a_shared_room_caution(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ "방 공유" 주의는 같은 방을 쓰는 묶음이 여럿일 때만 뜻이 있다 — 다른 시도의 줄이 섞일 상대가 없는 묶음에까지 달면, 덤프를
    런 루트에 모아 둔 정상 런마다 주의가 붙어 그 주의가 아무것도 가르지 못한다."""
    driven = await _short_run(db_session, monkeypatch, tmp_path)
    root = tmp_path / "root"
    _copy(driven.dump, root / "dumps" / DUMP_NAME)
    _copy(driven.log, root / "a" / "chat.jsonl")
    _write_manifest(root / "a", {"dump": "../dumps/prompt-dump.jsonl"})

    [bundle] = discover_bundles(root)

    assert (bundle.room_bundle_count, bundle.dump) == (1, (root / "dumps" / DUMP_NAME).resolve())
    assert bundle.cautions == []


async def test_a_bundle_that_fails_to_open_is_listed_as_unopenable_without_hiding_the_others(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """측정 기록은 사람이 고치거나 기록 중에 끊긴 파일이라 칸의 타입이 예상과 다를 수 있다(방 상태 칸이 문자열 등). 그런 묶음 하나의
    예외가 목록 전체를 막으면 나머지 런도 볼 수 없으므로, 그 묶음만 까닭과 함께 "열 수 없음"으로 싣는다."""
    driven = await _short_run(db_session, monkeypatch, tmp_path)
    root = tmp_path / "root"
    _copy(driven.log, root / "good" / "chat.jsonl")
    lines = _jsonl(driven.log)
    first_turn = next(r for r in lines if r["kind"] == "turn")
    first_turn["roomAfter"] = "깨진 값"
    (root / "bad").mkdir(parents=True)
    (root / "bad" / "chat.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in lines), encoding="utf-8"
    )

    entries = {entry.path: entry for entry in map(list_entry, discover_bundles(root))}

    assert (entries["good/chat.jsonl"].open_error, entries["good/chat.jsonl"].turn_count) == (None, 2)
    bad = entries["bad/chat.jsonl"]
    assert bad.supported and bad.open_error is not None and bad.turn_count is None
