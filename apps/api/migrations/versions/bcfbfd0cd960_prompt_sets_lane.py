"""prompt_sets lane

Revision ID: bcfbfd0cd960
Revises: 4e6d562bf8da
Create Date: 2026-09-17 21:15:05.271361

프롬프트 레인 분리(story/character/publish_filter)의 첫 단계 — `prompt_sets`에 `lane` 컬럼을 붙이고
인덱스 3개를 레인 축으로 교체한다. 문안 이관은 후속 리비전(`a69cbd40dec8`)이다.

**`lane`은 Postgres enum이 아니라 `Text`다** — `status`/`kind`/`channel`과 같은 관례고,
`apps/api/CLAUDE.md`의 "ENUM 3종 함정"(멤버 추가를 autogenerate가 감지 못 하는 것)을 피한다.
값은 `story`/`character`/`publish_filter` 3종 + 과도기 값 `legacy`(이 리비전이 백필하는 값,
아무 코드도 읽지 않는 격리 버킷) 4종.

**`server_default`는 이 리비전 안에서만 쓰고 뗀다** — `add_column`으로 기존 행을 전부
`'legacy'`로 백필한 뒤 같은 리비전에서 `alter_column(server_default=None)`으로 기본값을 뗀다.
모델(`db/models/prompt.py`)에는 기본값을 남기지 않는다. 기본값을 남기면 `PromptSet(...)` 생성
지점이 `lane`을 빠뜨려도 조용히 `'legacy'`가 되어 증상이 없다 — 기본값을 떼면 그 자리는 NOT
NULL 위반으로 즉시 터진다. **이 저장소에 `alter_column(server_default=...)` 선례는 0건**이다
(마이그레이션 24개 전수 grep — `alter_column`이 쓰인 5파일은 전부 `nullable=` 변경뿐이었다).
⚠️ **`alembic check`는 `server_default`를 비교하지 않는다**(`migrations/env.py`의
`context.configure(...)`에 `compare_server_default` 미지정, alembic 기본값 `False`) — 그래서
"기본값을 뗐다"는 이 파일의 `alembic check` 통과로 증명되지 않는다. 증명은 별도 직접 관측
(`information_schema.columns.column_default IS NULL`)이다.

인덱스 3건 교체 — `legal_documents`(`5bef71fc8f50`)와 글자 그대로 같은 모양이다:

| 이름 | 전 | 후 |
|---|---|---|
| `ix_prompt_sets_draft` | `UNIQUE (status) WHERE status='draft'` | `UNIQUE (lane) WHERE status='draft'` |
| `ix_prompt_sets_version_published` | `UNIQUE (version) WHERE status='published'` | 삭제 |
| `ix_prompt_sets_lane_version_published` | — | 신설 `UNIQUE (lane, version) WHERE status='published'` |
| `ix_prompt_sets_lane_published_at` | — | 신설 `(lane, published_at DESC)` |

`ix_prompt_sets_published_at`(`published_at DESC` 단독)은 건드리지 않는다 — 레인 분리 뒤에는 이
인덱스를 쓰는 실사용 쿼리가 남지 않지만(그 자리는 `ix_prompt_sets_lane_published_at`로 옮겨간다),
무관한 죽은 코드는 삭제하지 말고 언급하라는 규약 때문이다. 삭제는 별건.

`postgresql_where`는 전부 `sa.text(...)` 문자열이다 — bare `Mapped` 컬럼을 그대로 주면
autogenerate가 만드는 마이그레이션 소스에 `MappedColumn` 객체 repr이 박혀 `SyntaxError`가 나는
함정이 있다(`apps/api/CLAUDE.md`, `bd258b26c34a` 선례). 이 리비전은 `--autogenerate` 없이 손으로
썼지만 같은 형태를 유지한다.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'bcfbfd0cd960'
down_revision: str | Sequence[str] | None = '4e6d562bf8da'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default 로 기존 행을 전부 'legacy' 로 백필한 뒤 같은 리비전에서 뗀다.
    # 기본값을 남기면 PromptSet(...) 생성 지점이 lane 을 빠뜨려도 조용히 'legacy' 가 되고,
    # 그 행은 아무도 읽지 않으므로 증상이 없다.
    op.add_column(
        "prompt_sets",
        sa.Column("lane", sa.Text(), server_default="legacy", nullable=False),
    )
    op.alter_column("prompt_sets", "lane", server_default=None)

    op.drop_index(
        "ix_prompt_sets_draft", table_name="prompt_sets",
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.create_index(
        "ix_prompt_sets_draft", "prompt_sets", ["lane"], unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.drop_index(
        "ix_prompt_sets_version_published", table_name="prompt_sets",
        postgresql_where=sa.text("status = 'published'"),
    )
    op.create_index(
        "ix_prompt_sets_lane_version_published", "prompt_sets", ["lane", "version"], unique=True,
        postgresql_where=sa.text("status = 'published'"),
    )
    op.create_index(
        "ix_prompt_sets_lane_published_at", "prompt_sets",
        ["lane", sa.literal_column("published_at DESC")], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_prompt_sets_lane_published_at", table_name="prompt_sets")
    op.drop_index(
        "ix_prompt_sets_lane_version_published", table_name="prompt_sets",
        postgresql_where=sa.text("status = 'published'"),
    )
    op.create_index(
        "ix_prompt_sets_version_published", "prompt_sets", ["version"], unique=True,
        postgresql_where=sa.text("status = 'published'"),
    )
    op.drop_index(
        "ix_prompt_sets_draft", table_name="prompt_sets",
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.create_index(
        "ix_prompt_sets_draft", "prompt_sets", ["status"], unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.drop_column("prompt_sets", "lane")
