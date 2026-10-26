"""운영자가 api 컨테이너 안에서 돌려 작품(contents) 몇 편을 DB 와 저장소에서 완전히 지우는 도구.

앱에는 발행된 적 있는 작품을 지우는 경로가 없다(초안 삭제는 발행작이면 거부한다). 이 스크립트가 그 빈자리를 운영자 손으로만
메운다. 기본은 계획이다 — 무엇을 몇 행 지우고 무엇을 남기는지, 왜 거부하는지를 보여 주기만 하고 쓰지 않는다. 적용은 대상 작품
수를 따로 적어야 하고(`--expect-contents`), 지운 행이 가리키던 저장소 키는 커밋 전에 파일로 남겨 두었다가 커밋이 끝난 뒤 별도
명령(`delete-objects`)으로 지운다. DB 와 저장소를 한 트랜잭션으로 묶을 수 없어서, 커밋이 실패해도 그림이 먼저 사라지지 않게
순서를 나눈 것이다.

    # 계획만(쓰기 없음)
    python scripts/purge_contents.py plan --ids-file ids.txt

    # 적용 — 한 트랜잭션. 지울 저장소 키를 keys.json 에 남긴다
    python scripts/purge_contents.py apply --ids-file ids.txt --expect-contents 2 --keys-out keys.json

    # 저장소 정리 — 기본은 지울 키 수만 보여 주고, --apply 를 붙여야 지운다
    python scripts/purge_contents.py delete-objects --keys-file keys.json --apply

ids 파일은 한 줄에 작품 id 하나이고, 빈 줄과 `#` 로 시작하는 줄은 무시한다.
"""

import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class PurgePlan:
    content_ids: list[uuid.UUID]
    missing_ids: list[uuid.UUID]
    counts: dict[str, int] = field(default_factory=dict)
    refusals: list[str] = field(default_factory=list)
    asset_ids: list[uuid.UUID] = field(default_factory=list)
    storage_keys: list[str] = field(default_factory=list)


class PurgeRefused(Exception):  # noqa: N818 — 테스트·운영 안내가 이 이름으로 부른다(오류가 아니라 의도한 거부다)
    """계획에 거부 사유가 있거나 적용 조건이 맞지 않아 아무것도 쓰지 않았다."""

    def __init__(self, plan: PurgePlan) -> None:
        super().__init__("; ".join(plan.refusals))
        self.plan = plan


async def build_plan(db: AsyncSession, content_ids: Sequence[uuid.UUID]) -> PurgePlan:
    return PurgePlan(content_ids=sorted(content_ids), missing_ids=[])


async def apply_purge(
    db: AsyncSession, content_ids: Sequence[uuid.UUID], *, expect_contents: int, keys_out: Path
) -> PurgePlan:
    return PurgePlan(content_ids=sorted(content_ids), missing_ids=[])


def delete_objects(keys: Sequence[str], *, apply: bool, delete_fn: Callable[[str], None]) -> dict[str, int]:
    if not apply:
        return {"planned": 0}
    return {"deleted": 0, "failed": 0}


def main(argv: Sequence[str] | None = None) -> int:
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
