"""web·admin 의 원장 `kind` 라벨 맵이 `CloverKind` 전부를 덮는가.

두 맵은 `Record<string, string>` 이라(원장 `kind` 가 응답에서 `str` 이다) 키를 빠뜨려도 타입 검사가 못 잡고, 화면은 라벨 대신
`unit_conversion` 같은 원문을 보인다. web 은 자기 vitest 에도 같은 목록이 있지만 그 목록은 손 사본이라 BE 가 kind 를 더해도 따라
오지 않고, admin 에는 테스트 러너가 없다. 그래서 FE 소스를 그대로 읽어 BE 의 `CloverKind` 와 대조한다 — api 워크플로의 경로
필터에 두 파일이 들어 있다(없으면 FE 파일만 바뀐 PR 에서 이 검사가 돌지 않는다). 파일을 옮기면 그 필터도 함께 고친다.
"""

import re
from pathlib import Path
from typing import get_args

import pytest

from api.core.clover import CloverKind

REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_LABELS_TS = REPO_ROOT / "apps/web/src/entities/clover/model/cloverKindLabel.ts"
ADMIN_LABELS_TS = REPO_ROOT / "apps/admin/src/entities/admin-user/model/labels.ts"


def _label_keys(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    block = re.search(r"export const CLOVER_KIND_LABELS: Record<string, string> = \{(.*?)\n\};", source, re.DOTALL)
    assert block is not None, f"{path.name}: CLOVER_KIND_LABELS 를 못 찾았다 — 파일 모양이 바뀌었으면 이 정규식을 고칠 것"
    keys = set(re.findall(r'^\s+(\w+): "[^"]+",$', block.group(1), re.MULTILINE))
    assert keys, f"{path.name}: 키를 하나도 못 읽었다"
    return keys


@pytest.mark.parametrize("path", [pytest.param(WEB_LABELS_TS, id="web"), pytest.param(ADMIN_LABELS_TS, id="admin")])
def test_kind_label_map_covers_every_clover_kind(path: Path) -> None:
    assert _label_keys(path) == set(get_args(CloverKind))
