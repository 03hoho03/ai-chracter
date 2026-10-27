"""novel job llm calls

Revision ID: d59bf28caea5
Revises: 725813c4f950
Create Date: 2026-10-27 21:00:00.000000

소설 작업 행에 모델 호출 기록 칸(`novel_jobs.llm_calls`, JSONB, 기본값 `[]`, NOT NULL)을 더한다. 작업이 부른 호출마다 사용량·구현·
걸린 시간·소설 세트 id·단계·배정 출처·호출 실패 사유를 한 원소로 적어, 작업 종류 × 모델별 원가를 작업 단위로 되짚을 수 있게 한다.

**옛 이미지가 이 스키마 위에서 도는 구간**(배포 겹침, 이미지만 되돌린 동안, 교체 뒤에도 받은 작업을 마치는 옛 소설화 워커):
옛 코드는 칸을 매핑하지 않아 읽지도 쓰지도 않는다. 옛 코드의 작업 INSERT 는 칸을 비워 두고 서버 기본값 `[]` 이 채운다(그래서
기본값을 떼지 않는다). 옛 코드의 상태 전이 UPDATE 는 지정한 칸만 쓰므로 이 칸을 건드리지 않는다 — 옛 워커가 끝낸 작업은 기록이
`[]` 로 남는다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다. 상수 기본값이 있는 칸 추가는 표를 다시 쓰지 않는 메타데이터 변경이지만 그 순간
`novel_jobs` 에 `ACCESS EXCLUSIVE` 를 잡아야 한다. 그래서 이 표를 만진 채 열려 있는 트랜잭션(작업 요청·폴링·heartbeat·저장·환불)이
끝날 때까지 기다리고, 기다리는 동안 그 뒤의 작업 행 읽기·쓰기가 모두 이 잠금 뒤에 줄을 선다. 5초 안에 못 잡으면 실패시킨다(체인
전체 롤백, 다시 돌리면 된다).

**downgrade**: 칸만 지운다. 버리는 것은 작업마다의 호출 기록이고 사용자에게 보이지 않는 원가 분석 기록이라 지우기를 막는 가드는
두지 않는다(내린 뒤 다시 올려도 돌아오지 않는다 — 그 사이 행은 `[]` 이다). 칸을 지우는 순간 이 칸을 매핑한 새 이미지의 작업
INSERT 와 저장·환불 전이가 실패하므로 **이미지(api·소설화 워커)를 먼저 되돌린 뒤** 일회성 컨테이너로 내린다(옛 이미지는 이 칸이
있어도 돈다 — 이미지만 되돌리는 데에는 downgrade 가 필요 없다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d59bf28caea5"
down_revision: str | Sequence[str] | None = "725813c4f950"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "novel_jobs",
        sa.Column(
            "llm_calls",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("novel_jobs", "llm_calls")
