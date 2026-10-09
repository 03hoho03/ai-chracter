"""identity verification

Revision ID: bc4dd4fad61c
Revises: dd7fdcffccd7
Create Date: 2026-10-08 20:04:53.251783

휴대폰 본인인증 결과를 `users` 에 두 칸으로 남기고(`identity_ci_hmac`, `identity_verified_at`), 탈퇴한 사람의 CI 해시를
1년 보관하는 `withdrawn_identities` 를 만든다. CI 원문은 저장하지 않는다 — 서버 비밀키를 붙인 HMAC 만 남긴다.

- CHECK `ck_users_identity_pair`: 두 칸은 함께 있거나 함께 없다.
- 부분 유니크 `ux_users_identity_ci_hmac (identity_ci_hmac) WHERE deleted_at IS NULL`: 살아 있는 계정 사이에서만 한 사람
  한 계정이다. 탈퇴는 두 칸을 비우지만, 술어가 `deleted_at` 을 보므로 탈퇴 행이 같은 사람의 새 계정을 막지 않는다.
- `withdrawn_identities.claimed_mission_keys`: 그 사람이 탈퇴 전에 받은 1회성 미션 키. 같은 사람이 다시 가입해 인증해도
  보관 기간 안에는 같은 미션 보상을 다시 받지 못한다. 보관 기간이 지난 행은 백업 크론이 지운다.
- alembic 1.18.5 의 `alembic check` 는 CHECK 와 부분 인덱스의 WHERE 를 비교하지 않는다 — 행위 테스트가 유일한 검증이다.
  기존 테이블에 붙는 CHECK 는 autogenerate 가 만들지도 않아 손으로 더했다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다(떠 있는 API 가 `users` 를 늘 읽고 쓴다). NULL 칸 추가는 메타데이터만
바꾸고, CHECK 추가·부분 유니크 생성은 사용자 표를 한 번 훑는다(행 수가 작다).

**배포 겹침**(옛 색이 이 스키마에서 도는 구간) — 옛 코드는 두 칸을 모르고 쓰지 않는다. 새 CHECK 는 둘 다 NULL 인 행을
받아들이고, 부분 유니크는 NULL 을 서로 다르게 보므로 옛 쓰기를 거절하지 않는다. 옛 코드의 탈퇴는 두 칸을 비우지 않고
`withdrawn_identities` 도 쓰지 않는다 — 그 구간에 탈퇴한 인증자는 CI 해시가 탈퇴 행에 남고(부분 유니크 밖이라 재인증을
막지는 않는다) 미션 수령 기록이 남지 않는다. 게이트를 켜기 전에는 인증자가 없어 이 구간이 비어 있다.

**downgrade** — 인증된 사용자나 `withdrawn_identities` 행이 하나라도 있으면 멈춘다(`RuntimeError`). 되돌리면 1인 1계정
판정과 미션 재수령 차단의 근거가 사라진다. 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection


# revision identifiers, used by Alembic.
revision: str = 'bc4dd4fad61c'
down_revision: str | Sequence[str] | None = 'dd7fdcffccd7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assert_downgradable(conn: Connection) -> None:
    verified = conn.execute(sa.text("SELECT count(*) FROM users WHERE identity_ci_hmac IS NOT NULL")).scalar_one()
    withdrawn = conn.execute(sa.text("SELECT count(*) FROM withdrawn_identities")).scalar_one()
    if verified or withdrawn:
        raise RuntimeError(
            f"본인인증 기록이 있다(인증 회원 {verified}명, 탈퇴 인증 {withdrawn}행) — 되돌리면 1인 1계정 판정과 미션 재수령"
            " 차단의 근거가 사라진다. 옛 코드로 돌아가기만 하려면 downgrade 없이 이미지만 되돌린다(이 스키마에서 옛 코드가"
            " 그대로 돈다)."
        )


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column('users', sa.Column('identity_ci_hmac', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('identity_verified_at', sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        'ck_users_identity_pair',
        'users',
        '(identity_ci_hmac IS NULL) = (identity_verified_at IS NULL)',
    )
    op.create_index(
        'ux_users_identity_ci_hmac',
        'users',
        ['identity_ci_hmac'],
        unique=True,
        postgresql_where=sa.text('deleted_at IS NULL'),
    )
    op.create_table(
        'withdrawn_identities',
        sa.Column('ci_hmac', sa.Text(), nullable=False),
        sa.Column('withdrawn_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            'claimed_mission_keys', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.PrimaryKeyConstraint('ci_hmac'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    _assert_downgradable(op.get_bind())
    op.drop_table('withdrawn_identities')
    op.drop_index('ux_users_identity_ci_hmac', table_name='users', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_constraint('ck_users_identity_pair', 'users', type_='check')
    op.drop_column('users', 'identity_verified_at')
    op.drop_column('users', 'identity_ci_hmac')
