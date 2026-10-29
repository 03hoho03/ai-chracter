"""attendance claims

Revision ID: 02a8ea9563a1
Revises: 7caed2db87dc
Create Date: 2026-10-29 12:00:00.000000

누적 출석판의 수령 기록 `attendance_claims` 를 만들고, 탈퇴한 인증 회원 행에 그날 출석을 받았는지 남길
`withdrawn_identities.attendance_claimed_on` 을 더한다. 진도는 칸으로 두지 않고 이 표의 마지막 행에서 계산한다.
CHECK 둘은 alembic 1.18.5 의 `alembic check` 가 비교하지 않아 `IntegrityError` 행위 테스트가 유일한 검증이다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다(이 저장소 리비전 관례). 새 표는 비어 있고 FK 검사는 INSERT 때만 `users`·
`clover_ledger` 에 KEY SHARE 를 잡으므로 표를 만드는 일은 떠 있는 API 의 쓰기와 잠금이 겹치지 않는다. `withdrawn_identities` 에
NULL 허용 칸을 더하는 것은 메타데이터만 바꿔 표를 다시 쓰지 않는다.

**배포 겹침**(옛 색이 이 스키마에서 도는 구간) — 옛 코드는 이 표와 새 칸을 모르고 읽지도 쓰지도 않는다. 옛 코드의 탈퇴는
새 칸을 비워 두므로, 그 구간에 출석을 받고 탈퇴한 인증 회원은 같은 날 새 계정으로 한 번 더 받을 수 있다(스위치가 꺼진
채 배포하면 이 구간에 출석 행이 생기지 않는다).

**downgrade** — 출석 행이나 탈퇴 출석 날짜가 하나라도 있으면 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다. 표를 지우면 모든
회원의 판이 1판 1칸으로 돌아가고, 원장에는 그날 멱등키가 남아 다시 올렸을 때 오늘 수령이 "이미 받음"으로 막힌다. 옛 코드로
돌아가기만 하려면 downgrade 없이 이미지만 되돌린다(옛 코드는 이 표를 읽지 않는다). 테스트 세션 정리(`downgrade base`)에서는
표가 비어 있어 그대로 지운다 — 독립 커넥션으로 커밋하는 테스트는 정리 단계에서 자기 행을 먼저 지운다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '02a8ea9563a1'
down_revision: str | Sequence[str] | None = '7caed2db87dc'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('attendance_claims',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('board_no', sa.Integer(), nullable=False),
    sa.Column('reward_version', sa.SmallInteger(), nullable=False),
    sa.Column('seq', sa.SmallInteger(), nullable=False),
    sa.Column('claimed_on', sa.Date(), nullable=False),
    sa.Column('claimed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('ledger_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('seq BETWEEN 1 AND 28', name='ck_attendance_claims_seq_range'),
    sa.CheckConstraint('amount > 0', name='ck_attendance_claims_amount_positive'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_attendance_claims_user_id'),
    sa.ForeignKeyConstraint(['ledger_id'], ['clover_ledger.id'], name='fk_attendance_claims_ledger_id'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'claimed_on', name='ux_attendance_claims_user_id_claimed_on'),
    sa.UniqueConstraint('user_id', 'board_no', 'seq', name='ux_attendance_claims_user_id_board_no_seq'),
    )
    op.add_column('withdrawn_identities', sa.Column('attendance_claimed_on', sa.Date(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    conn = op.get_bind()
    claims = conn.execute(sa.text("SELECT count(*) FROM attendance_claims")).scalar_one()
    withdrawn = conn.execute(
        sa.text("SELECT count(*) FROM withdrawn_identities WHERE attendance_claimed_on IS NOT NULL")
    ).scalar_one()
    if claims or withdrawn:
        raise RuntimeError(
            f"attendance_claims 에 {claims}행, 탈퇴 출석 날짜가 {withdrawn}행 있다 — 표를 지우면 모든 회원의 출석판이 1판 1칸으로"
            " 돌아가고, 원장에 남은 그날 멱등키 때문에 다시 올렸을 때 오늘 수령이 이미 받은 것으로 막힌다. 탈퇴 출석 날짜를 지우면"
            " 그날 받고 탈퇴한 사람이 새 계정으로 한 번 더 받는다. 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다"
            " (옛 코드는 이 표와 칸을 읽지 않는다)."
        )
    op.drop_column('withdrawn_identities', 'attendance_claimed_on')
    op.drop_table('attendance_claims')
