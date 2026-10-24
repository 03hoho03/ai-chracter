"""prompt routes

Revision ID: 495e9a75bb46
Revises: 8b045061cad4
Create Date: 2026-10-24 12:00:00.000000

채팅 방 모델별로 단계마다 어느 프롬프트 체인을 읽고 어느 모델을 부를지 담을 표 둘을 더한다. 이 리비전만으로는 두 표를 읽거나
쓰는 코드가 없다.

- `prompt_routes`: (레인, 실효 방 모델, 단계)마다 한 행 — 읽을 체인 모델·부를 호출 모델·호출 경로. 유니크 인덱스
  `ix_prompt_routes_lane_room_model_stage`. 값 목록 CHECK 는 두지 않는다(단계를 늘릴 때마다 DROP → ADD 가 필요해지므로 값
  범위는 앱의 저장 검사가 맡는다). 행의 모양만 CHECK 둘로 지킨다: 생성 단계는 체인 모델을 두지 않고 나머지 단계는 반드시
  둔다(`ck_prompt_routes_generation_has_no_chain`), 생성 단계의 호출 모델은 방 모델과 같다
  (`ck_prompt_routes_generation_calls_room_model`, 대화 차감이 방 모델 단가라서). FK 없음.
- `prompt_route_revisions`: 저장 한 번 = 한 행, 저장한 표 전체를 JSONB 스냅샷으로 쌓는다. 저장 순번 `number` 는 양수 CHECK 와
  유니크 인덱스(동시 저장 둘이 같은 번호를 계산하면 뒤 커밋이 막힌다). 저장한 운영자 `admin_id` 는 `admin_users` FK, 되돌리기로
  만든 행의 원본 `restored_from_id` 는 자기 표 FK.

**옛 이미지가 이 스키마 위에서 도는 구간**(배포 겹침, 이미지만 되돌린 동안): 옛 코드는 두 표를 모르고 읽지도 쓰지도 않는다.
기존 표에는 칸을 더하지 않아 옛 코드의 INSERT·SELECT 는 그대로다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다 — 이력 표의 FK 를 만들 때 `admin_users` 에 `SHARE ROW EXCLUSIVE` 를 잠깐 잡으므로,
오래 걸린 트랜잭션 뒤에서 기다리며 어드민 요청을 줄 세우지 않게 5초 안에 못 잡으면 실패시킨다(다시 돌리면 된다).

**downgrade**: 이력 행이 하나라도 있으면 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다 — 어드민이 모델 배정을 저장한 뒤라 그
이력을 조용히 지우지 않는다. 옛 이미지는 이 표를 읽지 않으므로 이미지만 되돌리는 데에는 downgrade 가 필요 없다. 설정 표가 아니라
이력 표로 판정하는 이유는, 표를 비우는 저장도 이력 한 행을 남기므로 설정 표가 비어 있어도 쓴 적이 있는지는 이력 표만 알기
때문이다. 이력이 없으면 두 표를 지운다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "495e9a75bb46"
down_revision: str | Sequence[str] | None = "8b045061cad4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "prompt_routes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lane", sa.Text(), nullable=False),
        sa.Column("room_model", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("chain_model", sa.Text(), nullable=True),
        sa.Column("call_model", sa.Text(), nullable=False),
        sa.Column("backend", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(stage = 'chat_generate') = (chain_model IS NULL)", name="ck_prompt_routes_generation_has_no_chain"
        ),
        sa.CheckConstraint(
            "stage <> 'chat_generate' OR call_model = room_model",
            name="ck_prompt_routes_generation_calls_room_model",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_prompt_routes_lane_room_model_stage", "prompt_routes", ["lane", "room_model", "stage"], unique=True
    )

    op.create_table(
        "prompt_route_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("rows", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column("admin_id", sa.Uuid(), nullable=False),
        sa.Column("restored_from_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("number > 0", name="ck_prompt_route_revisions_number_positive"),
        sa.ForeignKeyConstraint(["admin_id"], ["admin_users.id"]),
        sa.ForeignKeyConstraint(["restored_from_id"], ["prompt_route_revisions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prompt_route_revisions_number", "prompt_route_revisions", ["number"], unique=True)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    saved = op.get_bind().execute(sa.text("SELECT count(*) FROM prompt_route_revisions")).scalar_one()
    if saved:
        raise RuntimeError(
            f"모델 배정 저장 이력 {saved}행이 남아 있다 — 어드민이 모델 배정을 저장한 뒤라 이력을 지우지 않는다. 옛 이미지는"
            " 이 표를 읽지 않으므로 이미지만 되돌린다."
        )
    op.drop_index("ix_prompt_route_revisions_number", table_name="prompt_route_revisions")
    op.drop_table("prompt_route_revisions")
    op.drop_index("ix_prompt_routes_lane_room_model_stage", table_name="prompt_routes")
    op.drop_table("prompt_routes")
