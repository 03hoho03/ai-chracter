"""novel v2 jobs

Revision ID: 3af53088351c
Revises: 4a4af1ac1df8
Create Date: 2026-10-06 23:55:00.000000

소설 작업 행(`novel_jobs`)을 여러 화 생성·부분 환불·연쇄 생성에 맞게 넓힌다.
- 새 칸: 환불액 `refunded_amount`, 연쇄 부모 `parent_job_id`, 대상 묶음 `batch_id`, 화 수 목표 `episode_count_target`,
  연쇄 부모가 고정하는 화 단가 `unit_price`, 연쇄 부모가 성공한 자식 몫을 쌓는 `consumed_amount`(기본 0).
- 종류에 연쇄 부모 `chain_generate`, 실패 사유에 출력 형식 위반 `malformed`·다시 만들기 화 수 불일치
  `episode_count_mismatch` 를 더한다. CHECK 의 값 목록은 모델 Literal 을 import 하지 않고 여기 리터럴로 적는다 — 나중에
  Literal 이 바뀌면 이 옛 리비전의 SQL 까지 바뀌기 때문이다.
- 진행 중 1건 부분 유니크를 연쇄 자식은 빼는 조건(`parent_job_id IS NULL`)으로 바꾼다. 연쇄 중에는 부모와 자식이 함께
  running 이다.
- 장·개정을 가리키는 FK 세 칸(`chapter_id`·`base_revision_id`·`result_revision_id`)에 인덱스가 없어 장·개정 DELETE 마다
  작업 테이블을 훑었다. 셋과 `parent_job_id` 에 인덱스를 더한다.

**환불 CHECK 교체** — 옛 `ck_novel_jobs_refund_only_when_failed`(환불은 실패에만)를 금액까지 보는
`ck_novel_jobs_refund_amount` 로 바꾼다. 갈래 셋:
1. 환불 없음: `refunded_at`·`refunded_amount` 둘 다 NULL.
2. 환불 있음: 실패면 쓰지 않은 몫 전부(`charged_amount - consumed_amount`, 0 초과), 성공이면 0 과 전액 사이의 부분 환불.
3. 옛 코드 호환: 실패 작업에 `refunded_at` 만 찍히고 금액이 NULL. 이미지만 되돌렸을 때 옛 코드의 환불은 금액 칸을 모른다
   — 막으면 그 환불이 500 이 된다. 읽는 쪽은 금액 NULL 을 전액 환불로 본다.
환불액 0 은 환불이 아니므로 `refunded_at` 도 찍지 않는다. 그래서 바꾸기 전에 차감 0 인데 `refunded_at` 이 찍힌 옛 행을
세어 `refunded_at` 을 비운다(옛 단가는 0 이 아니라 운영에는 없을 것으로 보지만, 있으면 새 CHECK 에 걸려 배포가 멈춘다).
그다음 환불된 옛 행에 `refunded_amount = charged_amount` 를 채운다(옛 환불은 모두 전액이었다).

첫 문장은 앞 리비전과 같은 `SET LOCAL lock_timeout = '5s'` 다(떠 있는 API 가 이 테이블을 읽는다). 같은 실행이면 이미
걸려 있지만, 이 리비전만 따로 올리는 경우에도 걸리게 한 번 더 둔다.

**downgrade** — 다음 행이 하나라도 있으면 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다. 옛 CHECK·부분 유니크가 그
행들을 받아들이지 못한다: 성공 + 환불(부분 환불), 종류 `chain_generate`, 실패 사유 `malformed`·`episode_count_mismatch`,
`parent_job_id` 가 있는 연쇄 자식. 그 밖에는 막지 않고 환불액·대상 묶음·화 수 목표·단가·소비액이 사라진다. 차감 0
행에서 비운 `refunded_at` 은 되살리지 않는다(옛 CHECK 는 NULL 을 받는다).

이 파일은 `api.*` 를 import 하지 않는다. 테스트(`tests/test_novel_v2_migration.py`)가 이 모듈을 `importlib` 로 불러
정리·백필·거부 판정 함수를 직접 부른다.

"""
from collections.abc import Sequence
import logging

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection


# revision identifiers, used by Alembic.
revision: str = '3af53088351c'
down_revision: str | Sequence[str] | None = '4a4af1ac1df8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

_OLD_KIND_CHECK = "kind IN ('chapter_generate', 'chapter_regenerate', 'ai_edit')"
_NEW_KIND_CHECK = "kind IN ('chapter_generate', 'chapter_regenerate', 'ai_edit', 'chain_generate')"
_OLD_FAILURE_CODE_CHECK = (
    "failure_code IS NULL OR failure_code IN ('llm_error', 'timeout', 'truncated', 'refused', 'blocked', 'empty',"
    " 'source_changed', 'expired', 'internal')"
)
_NEW_FAILURE_CODE_CHECK = (
    "failure_code IS NULL OR failure_code IN ('llm_error', 'timeout', 'truncated', 'refused', 'blocked', 'empty',"
    " 'source_changed', 'expired', 'internal', 'malformed', 'episode_count_mismatch')"
)
_OLD_REFUND_CHECK = "refunded_at IS NULL OR status = 'failed'"
_NEW_REFUND_CHECK = (
    "(refunded_at IS NULL AND refunded_amount IS NULL)"
    " OR (refunded_at IS NOT NULL AND refunded_amount IS NOT NULL AND ("
    "(status = 'failed' AND refunded_amount = charged_amount - consumed_amount AND refunded_amount > 0)"
    " OR (status = 'succeeded' AND refunded_amount > 0 AND refunded_amount < charged_amount)))"
    " OR (status = 'failed' AND refunded_at IS NOT NULL AND refunded_amount IS NULL)"
)
_OLD_ACTIVE_WHERE = "status IN ('queued', 'running')"
_NEW_ACTIVE_WHERE = "status IN ('queued', 'running') AND parent_job_id IS NULL"

# downgrade 를 막는 행. 이름은 오류 메시지에 그대로 나간다.
_DOWNGRADE_BLOCKERS: dict[str, str] = {
    "성공 + 환불(부분 환불)": "status = 'succeeded' AND refunded_at IS NOT NULL",
    "연쇄 부모(chain_generate)": "kind = 'chain_generate'",
    "실패 사유 malformed·episode_count_mismatch": "failure_code IN ('malformed', 'episode_count_mismatch')",
    "연쇄 자식(parent_job_id)": "parent_job_id IS NOT NULL",
}


def _clear_zero_charge_refunds(conn: Connection) -> int:
    """차감 0 인데 `refunded_at` 이 찍힌 행의 `refunded_at` 을 비우고 그 수를 돌려준다(위 docstring)."""
    cleared = conn.execute(
        sa.text("UPDATE novel_jobs SET refunded_at = NULL WHERE charged_amount = 0 AND refunded_at IS NOT NULL")
    ).rowcount
    if cleared:
        logger.warning("novel_jobs: 차감 0 인데 환불 시각이 찍힌 %d행의 refunded_at 을 비웠다", cleared)
    return cleared


def _backfill_refunded_amount(conn: Connection) -> int:
    """환불된 옛 행에 환불액(= 차감액)을 채우고 채운 행 수를 돌려준다. 이미 금액이 있는 행은 건드리지 않는다."""
    return conn.execute(
        sa.text(
            "UPDATE novel_jobs SET refunded_amount = charged_amount"
            " WHERE refunded_at IS NOT NULL AND refunded_amount IS NULL"
        )
    ).rowcount


def _downgrade_blockers(conn: Connection) -> dict[str, int]:
    """downgrade 를 막는 행을 종류별로 센다(0 인 종류는 뺀다)."""
    counts = {
        label: conn.execute(sa.text(f"SELECT count(*) FROM novel_jobs WHERE {condition}")).scalar_one()
        for label, condition in _DOWNGRADE_BLOCKERS.items()
    }
    return {label: count for label, count in counts.items() if count}


def _assert_downgradable(conn: Connection) -> None:
    blockers = _downgrade_blockers(conn)
    if blockers:
        found = ", ".join(f"{label} {count}행" for label, count in blockers.items())
        raise RuntimeError(
            f"novel_jobs 에 옛 스키마가 받을 수 없는 행이 있다: {found}. 옛 코드로 돌아가기만 하려면 downgrade 없이"
            " 이미지만 되돌린다(이 스키마에서 옛 코드가 그대로 돈다). 꼭 내려야 하면 진행 중 작업이 0 인 것을 본 뒤 그"
            " 행들을 정리하고 다시 돌린다 — 부분 환불 행은 refunded_at·refunded_amount 를 비우고(환불 원장은 남는다),"
            " 연쇄 부모·자식과 새 실패 사유 행은 차감·환불 원장과 대조해 기록을 남긴 뒤 지운다."
        )


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column('novel_jobs', sa.Column('refunded_amount', sa.Integer(), nullable=True))
    op.add_column('novel_jobs', sa.Column('parent_job_id', sa.Uuid(), nullable=True))
    op.add_column('novel_jobs', sa.Column('batch_id', sa.Uuid(), nullable=True))
    op.add_column('novel_jobs', sa.Column('episode_count_target', sa.Integer(), nullable=True))
    op.add_column('novel_jobs', sa.Column('unit_price', sa.Integer(), nullable=True))
    op.add_column('novel_jobs', sa.Column('consumed_amount', sa.Integer(), server_default='0', nullable=False))
    op.create_index('ix_novel_jobs_base_revision_id', 'novel_jobs', ['base_revision_id'], unique=False)
    op.create_index('ix_novel_jobs_chapter_id', 'novel_jobs', ['chapter_id'], unique=False)
    op.create_index('ix_novel_jobs_parent_job_id', 'novel_jobs', ['parent_job_id'], unique=False)
    op.create_index('ix_novel_jobs_result_revision_id', 'novel_jobs', ['result_revision_id'], unique=False)

    op.drop_constraint('ck_novel_jobs_kind', 'novel_jobs', type_='check')
    op.create_check_constraint('ck_novel_jobs_kind', 'novel_jobs', _NEW_KIND_CHECK)
    op.drop_constraint('ck_novel_jobs_failure_code', 'novel_jobs', type_='check')
    op.create_check_constraint('ck_novel_jobs_failure_code', 'novel_jobs', _NEW_FAILURE_CODE_CHECK)

    conn = op.get_bind()
    _clear_zero_charge_refunds(conn)
    _backfill_refunded_amount(conn)
    op.drop_constraint('ck_novel_jobs_refund_only_when_failed', 'novel_jobs', type_='check')
    op.create_check_constraint('ck_novel_jobs_refund_amount', 'novel_jobs', _NEW_REFUND_CHECK)

    op.drop_index('ux_novel_jobs_novel_id_active', table_name='novel_jobs', postgresql_where=sa.text(_OLD_ACTIVE_WHERE))
    op.create_index(
        'ux_novel_jobs_novel_id_active', 'novel_jobs', ['novel_id'], unique=True,
        postgresql_where=sa.text(_NEW_ACTIVE_WHERE),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    _assert_downgradable(op.get_bind())

    op.drop_index('ux_novel_jobs_novel_id_active', table_name='novel_jobs', postgresql_where=sa.text(_NEW_ACTIVE_WHERE))
    op.create_index(
        'ux_novel_jobs_novel_id_active', 'novel_jobs', ['novel_id'], unique=True,
        postgresql_where=sa.text(_OLD_ACTIVE_WHERE),
    )
    op.drop_constraint('ck_novel_jobs_refund_amount', 'novel_jobs', type_='check')
    op.create_check_constraint('ck_novel_jobs_refund_only_when_failed', 'novel_jobs', _OLD_REFUND_CHECK)
    op.drop_constraint('ck_novel_jobs_failure_code', 'novel_jobs', type_='check')
    op.create_check_constraint('ck_novel_jobs_failure_code', 'novel_jobs', _OLD_FAILURE_CODE_CHECK)
    op.drop_constraint('ck_novel_jobs_kind', 'novel_jobs', type_='check')
    op.create_check_constraint('ck_novel_jobs_kind', 'novel_jobs', _OLD_KIND_CHECK)

    op.drop_index('ix_novel_jobs_result_revision_id', table_name='novel_jobs')
    op.drop_index('ix_novel_jobs_parent_job_id', table_name='novel_jobs')
    op.drop_index('ix_novel_jobs_chapter_id', table_name='novel_jobs')
    op.drop_index('ix_novel_jobs_base_revision_id', table_name='novel_jobs')
    op.drop_column('novel_jobs', 'consumed_amount')
    op.drop_column('novel_jobs', 'unit_price')
    op.drop_column('novel_jobs', 'episode_count_target')
    op.drop_column('novel_jobs', 'batch_id')
    op.drop_column('novel_jobs', 'parent_job_id')
    op.drop_column('novel_jobs', 'refunded_amount')
