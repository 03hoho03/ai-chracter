"""novel sales stop

Revision ID: e9ad8ed93e90
Revises: c60f5b9b11bc
Create Date: 2026-10-19 21:29:29.111771

운영자의 "판매 중단" 두 갈래에 칸을 하나씩 더한다. 판매 중단은 목록·검색 노출과 새 판매만 멈추고 산 사람의 열람은 두며
환급하지 않는다 — 열람까지 닫고 환급하는 이용제한과 다른 조치다.

- `novel_publications.sales_stopped_at`(TIMESTAMPTZ NULL): 운영자가 이 공개 소설의 판매를 멈춘 시각. 비어 있으면 판매 중이다.
- `contents.novel_buyers_kept`(BOOLEAN NOT NULL DEFAULT false): 운영자가 이 원작을 이용제한·삭제하면서 파생 소설은 판매만
  멈추고 산 사람의 열람을 남기기로 골랐는가.

**이용제한 칸(`moderation_status`)에 새 값을 넣지 않고 칸을 따로 두는 이유**: 노벨 이용제한 칸의 값은 어드민 응답들과 작가의
공개 상태 응답에 Literal 로 실린다 — 새 값이 생긴 뒤 그 값을 모르는 옛 이미지로 되돌리면 그 응답들이 검증에서 500 이다. 또
판매 중단과 이용제한은 따로 걸리고 따로 풀린다 — 한 칸이면 판매 중단한 노벨을 이용제한했다가 해제할 때 해제가 `normal` 을
써서 판매 중단까지 함께 풀린다. 원작 쪽도 같다(원작 상태는 PG enum 이라 값을 더하려면 enum 을 바꿔야 하고, 그 값을 모르는
옛 이미지는 그 행을 읽다 실패한다). 대가도 있다 — 한 칸 안이었다면 옛 이미지의 목록 조건(`== 'normal'`)이 판매 중단 노벨을
계속 빼 주었을 텐데, 따로 둔 칸은 옛 이미지가 모른다(아래 되돌리기).

**`novel_buyers_kept` 에 CHECK 를 두지 않는 이유**: "제한·삭제일 때만 참" 같은 CHECK 를 걸면, 이 칸을 모르는 옛 이미지가
배포 겹침 동안 원작 제한을 해제(정상으로)할 때 표식이 그대로 남아 CHECK 위반 500 이 된다. 정상 원작의 남은 표식은 읽는 쪽이
보지 않는다(소장자 조건은 원작이 정상이 아닐 때만 이 칸을 본다).

**옛 이미지가 이 스키마 위에서 도는 구간**: 옛 코드는 두 칸을 읽지도 쓰지도 않는다 — 공개 행 INSERT 는 NULL, 작품 INSERT 는
false 로 채워진다. 그래서 `server_default` 를 떼지 않는다. 다만 새 코드가 칸을 쓴 뒤 옛 이미지로 되돌리면 옛 목록 조건이 판매
중단을 몰라 그 노벨이 다시 목록에 실리고 다시 팔리며, 옛 소장자 조건이 표식을 몰라 원작 판매 중단 노벨의 소장자가 환급 없이
열람을 잃는다 — 되돌리기 전 확인은 배포 문서에 있다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다 — 떠 있는 API 가 늘 읽는 두 표의 ALTER 라, 오래 걸린 트랜잭션 뒤에서 기다리며
뒤의 요청을 줄 세우지 않게 5초 안에 잠금을 못 잡으면 실패시킨다(다시 돌리면 된다). 두 칸 모두 상수 기본값이거나 NULL 이라 표를
다시 쓰지 않는다.

**downgrade**: 두 칸을 지운다. 판매 중단한 노벨은 다시 판매되고, 원작 판매 중단 노벨의 소장자는 열람을 잃는다(환급 없음).
이미지만 되돌릴 때는 downgrade 하지 않는다 — 옛 코드는 칸을 모른 채 돈다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9ad8ed93e90"
down_revision: str | Sequence[str] | None = "c60f5b9b11bc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("novel_publications", sa.Column("sales_stopped_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "contents", sa.Column("novel_buyers_kept", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("contents", "novel_buyers_kept")
    op.drop_column("novel_publications", "sales_stopped_at")
