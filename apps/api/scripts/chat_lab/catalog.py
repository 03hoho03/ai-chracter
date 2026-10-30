"""측정 서버가 들고 있는 런 목록과 결합 결과.

루트 탐색은 실데이터에서 수십 초라 한 번 훑은 묶음 목록을 들고 있다가 다시 훑으라고 할 때만 다시 훑는다(그때는 들고 있던 결합
결과도 버린다). 그 사이에는 묶음마다 파일 서명(드라이버 로그·짝 파일·같은 폴더의 기본 짝 이름과 매니페스트의 수정 시각과
크기)을 보고, 같으면 결합 결과를 다시 쓴다. 서명이 바뀌면 그 묶음의 짝을 다시 고른 뒤 다시 잇는다 — 진행 중인 측정이 줄을
덧붙이거나, 서버 밖에서 턴 기록을 내보내 기본 이름 짝이 새로 생겨도 다시 훑지 않고 반영된다. 새로 생긴 묶음만 다시 훑어야
보인다.

목록 항목은 묶음마다 들고 있고(작다), 결합 결과 자체는 최근 몇 묶음만 들고 있다 — 덤프가 든 결합 결과는 묶음 하나가 수 MB 라
루트 전체를 들고 있으면 메모리가 수백 MB 가 된다.

요청은 스레드 풀에서 오므로 잠금 하나로 줄 세운다."""

import threading
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from chat_lab.bundles import (
    CHAT_TURNS_NAME,
    DUMP_NAME,
    MANIFEST_NAME,
    SNAPSHOTS_NAME,
    Bundle,
    discover_bundles,
    repaired,
)
from chat_lab.join import JoinedRun, UnsupportedBundleError, join_bundle
from chat_lab.report import list_entry
from chat_lab.run_id import RunIdError, decode_run_id
from chat_lab.schemas import RunList, RunListItem

# 결합 결과를 들고 있는 묶음 수 — 화면은 한 번에 런 하나를 연다.
RECENT_JOINS = 8

Signature = tuple[tuple[str, int | None, int | None], ...]


class RunNotFoundError(LookupError):
    """그런 묶음이 없다(id 모양이 틀린 것 포함 — 측정 서버는 둘을 가르지 않고 404 로 낸다)."""


class BundleOpenError(Exception):
    """이 묶음은 열지 않거나(`unsupported`) 열다 실패했다(`openFailed`)."""

    def __init__(self, reason: Literal["unsupported", "openFailed"], message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _stat(path: Path) -> tuple[str, int | None, int | None]:
    try:
        stat = path.stat()
    except OSError:
        return str(path), None, None
    return str(path), stat.st_mtime_ns, stat.st_size


def signature(bundle: Bundle) -> Signature:
    folder = bundle.log.parent
    defaults = (folder / name for name in (MANIFEST_NAME, SNAPSHOTS_NAME, DUMP_NAME, CHAT_TURNS_NAME))
    pairs = (path for path in (bundle.snapshots, bundle.dump, bundle.chat_turns) if path is not None)
    return tuple(sorted({_stat(path) for path in (bundle.log, *defaults, *pairs)}))


class RunCatalog:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()
        self._bundles: list[Bundle] | None = None
        self._discovered_at = ""
        # 드라이버 로그 → 마지막으로 본 서명. 다르면 그 묶음의 짝을 다시 고른다.
        self._seen: dict[Path, Signature] = {}
        self._entries: dict[Path, tuple[Signature, RunListItem]] = {}
        self._recent: OrderedDict[Path, tuple[Signature, JoinedRun]] = OrderedDict()

    def _discovered(self, *, refresh: bool) -> list[Bundle]:
        if self._bundles is None or refresh:
            self._bundles = discover_bundles(self.root)
            self._discovered_at = datetime.now(UTC).isoformat()
            self._seen = {bundle.log: signature(bundle) for bundle in self._bundles}
            # 다시 훑으면 들고 있던 결과를 모두 버린다. 같은 방 묶음 수(방 공유 주의)처럼 다른 묶음이 생기거나 사라져 바뀌는 것은
            # 그 묶음의 파일 서명에 없어서, 서명이 같다고 다시 쓰면 낡은 주의가 남는다.
            self._entries.clear()
            self._recent.clear()
        return self._bundles

    def _current(self, index: int) -> tuple[Bundle, Signature]:
        assert self._bundles is not None
        bundle = self._bundles[index]
        sig = signature(bundle)
        if sig != self._seen.get(bundle.log):
            bundle = repaired(bundle)
            self._bundles[index] = bundle
            sig = signature(bundle)
            self._seen[bundle.log] = sig
        return bundle, sig

    def _index(self, run_id: str) -> int:
        try:
            path = decode_run_id(self.root, run_id)
        except RunIdError as error:
            raise RunNotFoundError(run_id) from error
        bundles = self._discovered(refresh=False)
        for index, bundle in enumerate(bundles):
            if bundle.log == path:
                return index
        raise RunNotFoundError(run_id)

    def _entry(self, index: int) -> RunListItem:
        bundle, sig = self._current(index)
        cached = self._entries.get(bundle.log)
        if cached is not None and cached[0] == sig:
            return cached[1]
        item = list_entry(bundle)
        self._entries[bundle.log] = (sig, item)
        return item

    def runs(self, *, refresh: bool = False) -> RunList:
        with self._lock:
            bundles = self._discovered(refresh=refresh)
            items = [self._entry(index) for index in range(len(bundles))]
            return RunList(items=items, discovered_at=self._discovered_at)

    def find(self, run_id: str) -> Bundle:
        """없으면 `RunNotFoundError`."""
        with self._lock:
            return self._current(self._index(run_id))[0]

    def joined(self, run_id: str) -> JoinedRun:
        """없으면 `RunNotFoundError`, 열지 않는 형식이거나 열다 실패하면 `BundleOpenError`."""
        with self._lock:
            bundle, sig = self._current(self._index(run_id))
            cached = self._recent.get(bundle.log)
            if cached is not None and cached[0] == sig:
                self._recent.move_to_end(bundle.log)
                return cached[1]
            try:
                joined = join_bundle(bundle)
            except UnsupportedBundleError as error:
                raise BundleOpenError("unsupported", str(error)) from error
            except Exception as error:  # 목록이 "열 수 없음"으로 싣는 것과 같은 범위다(`list_entry`).
                raise BundleOpenError("openFailed", f"{type(error).__name__}: {error}") from error
            self._recent[bundle.log] = (sig, joined)
            self._recent.move_to_end(bundle.log)
            while len(self._recent) > RECENT_JOINS:
                self._recent.popitem(last=False)
            return joined

    def entry(self, run_id: str) -> RunListItem:
        """그 묶음의 목록 항목(서명이 바뀌었으면 다시 이은 것). 내보내기 뒤 화면이 받는 항목이다."""
        with self._lock:
            return self._entry(self._index(run_id))
