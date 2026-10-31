"""런 루트를 훑어 묶음을 찾는다 — 묶음은 드라이버 로그 하나(턴 줄이 1개 이상이고 방 id 가 하나인 jsonl)와 그 짝 파일이다.

드라이버 로그는 이름이 아니라 내용으로 찾는다. 옛 측정은 드라이버 로그를 `turns.jsonl`·`smoke.jsonl` 같은 이름으로 썼다. 다만
훑는 비용 때문에 첫 줄의 `kind` 가 드라이버가 쓰는 종류인 파일만 끝까지 읽는다(덤프·스냅숏·턴 기록은 첫 줄에서 빠진다).

짝 파일은 같은 폴더의 기본 이름(`memory-snapshots.jsonl`·`prompt-dump.jsonl`·`chat-turns.jsonl`)을 쓰고, 없으면 그 폴더의 매니페스트
`chat-lab.json` 이 가리키는 파일을 쓴다. `turns.jsonl` 은 짝이 아니다 — 옛 드라이버 로그의 이름이라 짝으로 읽으면 드라이버 로그를
턴 기록으로 연다. 같은 폴더 밖 파일은 매니페스트로만 잇는다. 같은 방을 여러 묶음이 쓰면(체크포인트 복원·가지치기 측정) 조상
폴더의 덤프를 방 id 로 걸러도 다른 시도의 줄이 섞이기 때문이다. 그래서 같은 방 묶음이 둘 이상인데 매니페스트로 같은 폴더 밖
짝을 쓴 묶음에는 "방 공유" 주의를 단다. 매니페스트 경로는 묶음 폴더 기준 상대 경로이고, resolve 한 뒤 런 루트 안이어야 한다.

형식 세대: 턴 줄에 방 id 가 없으면 옛 형식(목록에만 보이고 열지 않는다), 턴 줄에 `shortcutId`·`assistantMessageId` 가 하나라도
있으면 지금 형식, 둘 다 없으면 `assistantMessageId` 이전 형식(턴 기록과 이을 수 없다). `shortcutId` 는 지금 드라이버가 실패한 턴
줄에도 늘 쓰고 `assistantMessageId` 는 응답을 받은 줄에만 쓴다."""

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from chat_lab.run_id import decode_run_id, encode_run_id
from chat_lab.schemas import BundleFormat, Caution

SNAPSHOTS_NAME = "memory-snapshots.jsonl"
DUMP_NAME = "prompt-dump.jsonl"
CHAT_TURNS_NAME = "chat-turns.jsonl"
MANIFEST_NAME = "chat-lab.json"
# 매니페스트 키 → 기본 짝 이름. `chat` 은 매니페스트가 어느 드라이버 로그의 것인지다(없으면 `chat.jsonl`).
MANIFEST_PAIRS = {"snapshots": SNAPSHOTS_NAME, "dump": DUMP_NAME, "turns": CHAT_TURNS_NAME}
DEFAULT_CHAT_NAME = "chat.jsonl"
# 대량 시도 폴더 — 그 아래 묶음은 이 폴더까지의 경로를 묶음 키로 받아 목록에서 접힌다.
GROUPED_DIR_NAMES = frozenset({"probes"})
# 측정 드라이버(`scripts/chat_play.py`)와 옛 드라이버가 쓰는 줄 종류. 첫 줄이 이것이 아니면 드라이버 로그로 읽지 않는다.
DRIVER_KINDS = frozenset(
    {
        "meta",
        "opening",
        "login",
        "relogin",
        "rebase",
        "turn",
        "pause",
        "noteUpdate",
        "check",
        "preCheck",
        "regenerate",
        "edit",
    }
)


@dataclass(frozen=True)
class JsonlFile:
    records: list[dict[str, Any]]
    cautions: list[Caution]


def read_jsonl(path: Path) -> JsonlFile:
    """줄마다 JSON 객체 하나. 바이트를 개행으로 나눈 뒤 줄마다 UTF-8 로 디코드한다 — 파일 전체를 한 번에 디코드하면 기록 중에
    여러 바이트 글자 가운데서 잘린 마지막 줄 하나 때문에 파일 전체가 읽히지 않는다(`splitlines` 는 문자열 안의 U+2028 같은
    글자에서도 끊으므로 쓰지 않는다). 읽히지 않는 마지막 줄은 기록 중에 잘린 줄로 보고 버린 뒤 주의로, 그 밖의 읽지 못한 줄도
    건너뛰고 주의로 남긴다 — 줄 하나 때문에 묶음 전체가 열리지 않게 하지 않는다."""
    chunks = path.read_bytes().split(b"\n")
    records: list[dict[str, Any]] = []
    cautions: list[Caution] = []
    for number, chunk in enumerate(chunks, start=1):
        if not chunk.strip():
            continue
        try:
            record = json.loads(chunk.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            if number == len(chunks):
                cautions.append(Caution(kind="incompleteLine", detail=f"{path.name} 마지막 줄({number})이 잘려 버렸다"))
            else:
                cautions.append(
                    Caution(kind="unreadableLine", detail=f"{path.name} {number}번째 줄을 읽지 못해 건너뛰었다")
                )
            continue
        if isinstance(record, dict):
            records.append(record)
        else:
            cautions.append(Caution(kind="unreadableLine", detail=f"{path.name} {number}번째 줄이 JSON 객체가 아니다"))
    return JsonlFile(records=records, cautions=cautions)


def _first_kind(path: Path) -> object:
    with path.open("rb") as handle:
        for line in handle:
            if line.strip():
                try:
                    record = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    return None
                return record.get("kind") if isinstance(record, dict) else None
    return None


def bundle_format(records: list[dict[str, Any]]) -> BundleFormat:
    turns = [r for r in records if r.get("kind") == "turn"]
    if any("roomId" not in r for r in turns):
        return "legacy"
    if any("shortcutId" in r or "assistantMessageId" in r for r in turns):
        return "current"
    return "preMessageId"


@dataclass
class Bundle:
    root: Path
    log: Path
    run_id: str
    path: str
    room_id: str
    format: BundleFormat
    group: str | None
    snapshots: Path | None
    dump: Path | None
    chat_turns: Path | None
    # 같은 방 id 를 가진 묶음 수(이 묶음 포함).
    room_bundle_count: int = 1
    cautions: list[Caution] = field(default_factory=list)
    # 짝 파일 가운데 같은 폴더 밖을 가리키는 것이 있다(매니페스트로만 생긴다).
    uses_outside_folder: bool = False

    @property
    def supported(self) -> bool:
        return self.format != "legacy"


def _group(relative: PurePosixPath) -> str | None:
    parts = relative.parts[:-1]
    for index, part in enumerate(parts):
        if part in GROUPED_DIR_NAMES:
            return PurePosixPath(*parts[: index + 1]).as_posix()
    return None


def _manifest(folder: Path) -> tuple[dict[str, Any] | None, list[Caution]]:
    path = folder / MANIFEST_NAME
    if not path.is_file():
        return None, []
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None, [Caution(kind="manifest", detail=f"{MANIFEST_NAME} 를 JSON 으로 읽을 수 없다")]
    if not isinstance(manifest, dict):
        return None, [Caution(kind="manifest", detail=f"{MANIFEST_NAME} 가 객체가 아니다")]
    return manifest, []


def _manifest_path(root: Path, folder: Path, key: str, value: object) -> tuple[Path | None, Caution | None]:
    """매니페스트 항목 하나를 루트 안의 파일로. 상대 경로가 아니거나 resolve 한 뒤 루트 밖·파일이 아니면 버린다."""
    if not isinstance(value, str) or not value or PurePosixPath(value).is_absolute():
        return None, Caution(kind="manifest", detail=f"{MANIFEST_NAME} 의 {key} 는 묶음 폴더 기준 상대 경로여야 한다")
    resolved = (folder / value).resolve()
    if not resolved.is_relative_to(root):
        return None, Caution(kind="manifest", detail=f"{MANIFEST_NAME} 의 {key} 가 런 루트 밖을 가리킨다")
    if not resolved.is_file():
        return None, Caution(kind="manifest", detail=f"{MANIFEST_NAME} 의 {key} 파일이 없다")
    return resolved, None


def _pair_files(root: Path, log: Path) -> tuple[dict[str, Path | None], list[Caution]]:
    folder = log.parent
    manifest, cautions = _manifest(folder)
    if manifest is not None and manifest.get("chat", DEFAULT_CHAT_NAME) != log.name:
        manifest = None
    pairs: dict[str, Path | None] = {}
    for key, name in MANIFEST_PAIRS.items():
        default = folder / name
        listed = manifest.get(key) if manifest is not None else None
        if default.is_file() and not default.is_symlink():
            pairs[key] = default
            if listed is not None and listed != name:
                cautions.append(Caution(kind="manifest", detail=f"{key} 는 같은 폴더 기본 이름 {name} 을 썼다"))
            continue
        pairs[key] = None
        if listed is not None:
            path, caution = _manifest_path(root, folder, key, listed)
            pairs[key] = path
            if caution is not None:
                cautions.append(caution)
    return pairs, cautions


def _driver_log(path: Path) -> tuple[str, BundleFormat] | None:
    """드라이버 로그면 (방 id, 형식). 턴 줄이 없거나 방 id 가 하나가 아니면 묶음이 아니다. 읽지 못하는 파일(권한·사라짐)은
    묶음이 아닌 것으로 치고 넘어간다 — 파일 하나 때문에 루트 전체 탐색이 멈추지 않게."""
    try:
        if _first_kind(path) not in DRIVER_KINDS:
            return None
        records = read_jsonl(path).records
    except (OSError, UnicodeDecodeError):
        return None
    if not any(r.get("kind") == "turn" for r in records):
        return None
    rooms = {r["roomId"] for r in records if isinstance(r.get("roomId"), str)}
    if len(rooms) != 1:
        return None
    return rooms.pop(), bundle_format(records)


def _paired(base: Path, path: Path, room_id: str, form: BundleFormat) -> Bundle:
    relative = PurePosixPath(path.relative_to(base).as_posix())
    pairs, cautions = _pair_files(base, path)
    return Bundle(
        root=base,
        log=path,
        run_id=encode_run_id(base, path),
        path=relative.as_posix(),
        room_id=room_id,
        format=form,
        group=_group(relative),
        snapshots=pairs["snapshots"],
        dump=pairs["dump"],
        chat_turns=pairs["turns"],
        cautions=cautions,
        uses_outside_folder=any(p is not None and p.parent != path.parent for p in pairs.values()),
    )


def _count_room(bundle: Bundle, count: int) -> None:
    bundle.room_bundle_count = count
    if count > 1 and bundle.uses_outside_folder:
        bundle.cautions.append(
            Caution(
                kind="roomShared",
                detail=f"이 방을 묶음 {count}개가 쓴다 — 같은 폴더 밖 짝 파일에 다른 시도의 줄이 섞였을 수 있다",
            )
        )


def discover_bundles(root: Path, *, folder: Path | None = None) -> list[Bundle]:
    """루트 아래 묶음 전부(경로 순). 링크는 따라가지 않는다. `folder`(루트 안)를 주면 그 폴더 바로 아래 파일만 본다 — 묶음
    하나를 다루는 명령이 루트 전체(실측 수십 초)를 훑지 않게. 그때 같은 방 묶음 수도 그 폴더 안에서만 센다."""
    base = root.resolve()
    candidates = base.rglob("*.jsonl") if folder is None else folder.resolve().glob("*.jsonl")
    bundles: list[Bundle] = []
    for path in sorted(candidates):
        relative = PurePosixPath(path.relative_to(base).as_posix())
        if any((base / part).is_symlink() for part in (relative, *relative.parents[:-1])) or not path.is_file():
            continue
        found = _driver_log(path)
        if found is None:
            continue
        room_id, form = found
        bundles.append(_paired(base, path, room_id, form))
    counts = Counter(bundle.room_id for bundle in bundles)
    for bundle in bundles:
        _count_room(bundle, counts[bundle.room_id])
    return bundles


def repaired(bundle: Bundle) -> Bundle:
    """같은 드라이버 로그로 짝 파일을 다시 고른 묶음. 묶음을 찾은 뒤 턴 기록 파일이 새로 생기거나 매니페스트가 바뀌었을 때
    루트 전체를 다시 훑지 않고 그 묶음만 고친다. 같은 방 묶음 수는 찾을 때 센 값을 그대로 쓴다."""
    fresh = _paired(bundle.root, bundle.log, bundle.room_id, bundle.format)
    _count_room(fresh, bundle.room_bundle_count)
    return fresh


def find_bundle(bundles: list[Bundle], root: Path, run_id: str) -> Bundle | None:
    """id 가 가리키는 묶음. id 모양이 틀리면 `RunIdError`, 모양은 맞는데 그런 묶음이 없으면 None."""
    path = decode_run_id(root, run_id)
    return next((bundle for bundle in bundles if bundle.log == path), None)
