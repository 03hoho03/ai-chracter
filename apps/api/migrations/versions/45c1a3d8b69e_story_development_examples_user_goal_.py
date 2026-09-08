"""story development examples user goal rules

Revision ID: 45c1a3d8b69e
Revises: e933fcbb7938
Create Date: 2026-09-09 01:12:17.016730

chat-goal-prompt.md §8-3 / chat-techspec.md §6-2 (D-13) — revision ① of two: adds the new
columns and backfills `development_examples` by parsing the existing `development_example`
free text in Python (not SQL regex). Revision ② (dropping `development_example`) is out of
scope for this run — it happens after the backfill is eyeballed in production.

Parsing rule (chat-techspec.md §6-2, 실측): 발행 30개 전수 — `사용자:` 30/30, `서술자:` 29/30,
`진행자:` 1/30(우리 프롬프트가 실제로 쓰는 라벨). Text is split at those two label kinds and
paired up in order. If no label is found at all, or the text doesn't *start* with a user
label (one seed entry opens with a narrator line before any user line), we can't confidently
reconstruct the original turn order — the whole text goes into a single pair's
`assistantLine` with an empty `userLine` instead of guessing (데이터를 버리지 않는다).
"""
import json
import re
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '45c1a3d8b69e'
down_revision: str | Sequence[str] | None = 'e933fcbb7938'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_USER = re.compile(r"(?:^|\n)\s*사용자\s*:")
_ASSISTANT = re.compile(r"(?:^|\n)\s*(?:서술자|진행자)\s*:")


def _parse_development_example(source: str) -> list[dict[str, str]]:
    labels = sorted(
        [(m.start(), m.end(), "user") for m in _USER.finditer(source)]
        + [(m.start(), m.end(), "assistant") for m in _ASSISTANT.finditer(source)]
    )
    if not labels or labels[0][2] != "user" or source[: labels[0][0]].strip():
        return [{"userLine": "", "assistantLine": source.strip()}]

    segments: list[tuple[str, str]] = []
    for i, (_start, end, kind) in enumerate(labels):
        seg_end = labels[i + 1][0] if i + 1 < len(labels) else len(source)
        segments.append((kind, source[end:seg_end].strip()))

    pairs: list[dict[str, str]] = []
    i = 0
    while i < len(segments):
        kind, content = segments[i]
        if kind == "user":
            if i + 1 < len(segments) and segments[i + 1][0] == "assistant":
                pairs.append({"userLine": content, "assistantLine": segments[i + 1][1]})
                i += 2
            else:
                pairs.append({"userLine": content, "assistantLine": ""})
                i += 1
        else:
            # stray assistant segment with no preceding user line (only reached when
            # labels[0] is "user" but a later run of assistant segments repeats)
            pairs.append({"userLine": "", "assistantLine": content})
            i += 1
    return pairs


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'story_version_details',
        sa.Column(
            'development_examples',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column('story_version_details', sa.Column('user_goal', sa.Text(), nullable=True))
    op.add_column('story_version_details', sa.Column('rules', sa.Text(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT content_version_id, development_example FROM story_version_details")
    ).fetchall()
    for content_version_id, development_example in rows:
        if not development_example:
            continue
        pairs = _parse_development_example(development_example)
        bind.execute(
            sa.text(
                "UPDATE story_version_details SET development_examples = CAST(:pairs AS jsonb) "
                "WHERE content_version_id = :id"
            ),
            {"pairs": json.dumps(pairs), "id": content_version_id},
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('story_version_details', 'rules')
    op.drop_column('story_version_details', 'user_goal')
    op.drop_column('story_version_details', 'development_examples')
