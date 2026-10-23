"""novel block edit schema

Revision ID: a8708e3535d5
Revises: b389c2317149
Create Date: 2026-10-24 10:00:00.000000

여러 문단 수정이 쓸 칸을 더한다. `novel_jobs.block_edit`(JSONB, NULL 허용) — 대상 블록·블록마다의 패치·묶음을 담는다. 이 칸이 있는
작업은 AI 수정이고 문단 범위·장 전체 결과 본문 칸을 쓰지 않는다(CHECK `ck_novel_jobs_block_edit`).

**옛 이미지가 이 스키마 위에서 도는 구간**(배포 겹침, 이미지만 되돌린 동안): 옛 코드는 칸을 매핑하지 않아 읽지도 쓰지도 않는다.
옛 코드의 작업 INSERT 는 칸을 비워 두고 CHECK 는 칸이 있는 행에만 걸린다. 옛 코드가 패치 작업 행을 만나면 — 상세의 미적용 목록과
낡은 미리보기 비우기는 결과 본문이 있는 행만 보아 지나치고, 적용은 범위가 비어 409, 버리기는 버린 시각·지시문·결과 본문만 써서
CHECK 를 통과한다(패치 칸은 그대로 남는다). 이 리비전만으로는 칸을 쓰는 코드가 없고, 쓰는 라우트는 스위치가 꺼진 채 배포된다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다 — 떠 있는 API 가 늘 쓰는 `novel_jobs` 를 ALTER 하므로 오래 걸린 트랜잭션 뒤에서 기다리며
뒤의 요청을 줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(다시 돌리면 된다). NULL 칸 추가는 표를 다시 쓰지 않고, CHECK 를 거는 표
훑기는 작업 표가 작아 짧다(같은 트랜잭션이라 `NOT VALID` 로 나눠도 잠금 시간은 같다).

**downgrade**: 대기 패치가 남은 행(사용자 글에서 나온 문단이 들어 있다)이나 진행 중인 패치 작업(끝나면 대기 패치가 생긴다)이 하나라도
있으면 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다 — 칸을 지운 옛 스키마에서는 그 문단을 지우는 코드가 없어 화를 지워도 남는다.
끝난 패치 작업(적용·버림·낡음 상태와 블록 id 만 남은 기록)은 칸과 함께 버린다. 칸을 지우는 순간 이 칸을 매핑한 새 이미지의 작업 조회가
모두 실패하므로 **이미지를 먼저 되돌린 뒤** 일회성 컨테이너로 내린다(옛 이미지는 이 칸이 있어도 돈다 — 이미지만 되돌리는 데에는
downgrade 가 필요 없다). 위에 쌓인 문안 리비전을 먼저 내린다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8708e3535d5"
down_revision: str | Sequence[str] | None = "b389c2317149"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = (
    "block_edit IS NULL OR (kind = 'ai_edit' AND result_text IS NULL"
    " AND paragraph_start IS NULL AND paragraph_end IS NULL)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("novel_jobs", sa.Column("block_edit", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_check_constraint("ck_novel_jobs_block_edit", "novel_jobs", _CHECK)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    left = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM novel_jobs WHERE block_edit IS NOT NULL AND ("
            " status IN ('queued', 'running')"
            " OR jsonb_path_exists(block_edit, '$.patches[*] ? (@.state == \"pending\")'))"
        )
    ).scalar_one()
    if left:
        raise RuntimeError(
            f"대기 패치가 남았거나 진행 중인 여러 문단 수정 작업 {left}행이 남아 있다 — 칸을 지우면 그 문단을 지울 코드가 없다."
            " 스위치를 끄고 진행 중 작업이 끝나기를 기다린 뒤 남은 패치를 버리고 다시 내린다. 옛 이미지는 이 칸이 있어도 돈다."
        )
    op.drop_constraint("ck_novel_jobs_block_edit", "novel_jobs", type_="check")
    op.drop_column("novel_jobs", "block_edit")
