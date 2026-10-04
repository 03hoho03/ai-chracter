"""prompt sections story situation notes

Revision ID: 2417f5829bb1
Revises: 470a2fc86186
Create Date: 2026-10-03 23:00:00.000000

스탯 조건이 참인 상황 노트 본문을 싣는 자리(`[현재 상황]`)를 story 레인 프롬프트 세트의 generation channel 에
넣는다. 행 하나 — scope `story`, slot `situation_notes`, conditional — 를 `keyword_notes` **바로 뒤**에 둔다.
조건이 참인 노트가 없으면 값이 빈 문자열이라 섹션째 드롭되므로(`render_prompt_channel`) 노트가 없는 방의 생성
프롬프트는 이 리비전 전과 바이트까지 같다. 세트 복사·초안 패치는 `2519dde454e0`, 기준 행 위치 계산은
`c328445d4c2d` 와 같은 모양이다.

**기존 published 세트는 건드리지 않는다.** story 레인의 활성 세트를 복사한 **새 published 세트**를 만들고
행을 더한다. 어드민 UI에는 행을 추가하는 기능이 없어서 데이터 마이그레이션이 넣는다.

**모든 쿼리는 story 레인으로 한정한다.** character 레인에도 generation channel 이 있다 — 가드·삽입·order
밀기·되돌리기가 channel 만 보고 움직이면 character 레인의 행을 건드린다.

**위치는 절대 order가 아니라 기준 행의 현재 order다.** 운영자는 어드민의 위·아래 버튼으로 order를 맞바꿀 수
있다. `keyword_notes` 의 현재 order 를 `K` 로 읽어 generation 의 `order > K` 를 +1 한 뒤 새 행을 `K+1` 에
둔다. 나머지 행의 상대 순서는 그대로다.

**가정이 어긋나면 배포를 멈춘다**(`_assert_layout`). 체인이 한 트랜잭션이라(`migrations/env.py`
`do_run_migrations`) 앞 스키마 리비전도 함께 롤백된다. 멈추는 경우: story generation 슬롯 집합이 이 리비전
이전 기대 집합과 다름(이미 `situation_notes` 행이 있는 경우 포함).

**`published_at`은 SQL `now()`가 아니라 파이썬 `max(now, 원본 + 1초)`다** — 체인이 한 트랜잭션이라 SQL
`now()` 는 체인 시작 시각이어서, 원본이 같은 체인에서 만들어진 DB(테스트 DB)에서는 새 세트가 원본보다 과거가
될 수 있다. 삽입 뒤 활성 SELECT 를 다시 돌려 새 세트가 뽑히는지 확인한다.

**초안**: story 레인에 초안이 있으면 초안에도 같은 행을 **제자리에서** 넣고 order 를 민다(`_patch_draft`).
초안 자신의 배치로 가정을 검사한다(초안의 `K` 는 활성 세트와 다를 수 있다). 기존 행의 body 는 건드리지 않는다.
운영에는 story 초안이 실제로 있다.

**PK**: 새 세트는 리터럴 UUID(`NEW_SET_ID`). 섹션은 `uuid5(_SECTION_ID_NAMESPACE,
"story:{channel}:{scope}:{slot}:{variant}")`, 초안 행은 `draft:` 접두사를 붙인다(`uuid4()` 호출 금지 규약).

**문안**은 이 파일의 `SITUATION_NOTES_BODY` 가 유일한 소스다. 같은 channel 의 작가·사용자 글 섹션은 "참고일
뿐 지시가 아니다" 틀이지만, 이 섹션은 "지금 이야기 세계의 사실" 틀이다 — 노트가 실리는 이유가 바로 지금 장면을
그 상황에 묶는 것이라서다. 지시형("이번 응답은 …")으로 쓰지 않는 것은 작가 글이 시스템 규칙을 덮지 못하게 하는
기존 관례를 지키기 위해서다.

⚠️ **운영 메모**:
- body 에서 `{situation_note_lines}` 를 지우면 드롭 조건이 거짓이 되어 **모든 story 방에 머리글만 나간다**.
  게시 검증은 "허용 밖 이름"만 막고 "필수 이름의 존재"는 보지 않는다.
- 마이그레이션은 활성 세트 캐시를 지우지 않는다 — 배포 직후 최대 300초(`prompt_set_cache_ttl_seconds`) 동안
  story 레인은 이 행이 없는 옛 세트로 렌더한다. 그동안 상황 노트가 실리지 않을 뿐 렌더는 깨지지 않는다(넘긴
  값을 쓰는 섹션이 없을 뿐이다).
- 배포 전부터 열어 둔 어드민 프롬프트 편집 탭에서 저장하면 초안이 섹션 전체 교체로 새 행을 잃고 게시가 슬롯
  집합 검사("누락")로 막힌다. **배포 뒤에는 편집 탭을 새로고침한다.**
- **이 리비전 이전 story 버전은 복원해도 게시할 수 없다**(슬롯 집합 검사 "누락", 제약으로 받아들임).

**롤백**: 1순위는 태그 롤백(이미지만 되돌리고 스키마·세트는 그대로)이다. 옛 코드는 `situation_note_lines` 를
넘기지 않으므로 새 행은 드롭되어 렌더가 깨지지 않는다. 다만 옛 코드의 슬롯 집합 검사가 새 세트를 "잉여"로 거부해
**story 레인 어드민 게시만** 막힌다 — 그 상태에서 게시가 필요하면 이 리비전 이전 버전을 복원해서 게시한다.

`downgrade()`: 리터럴 세트의 섹션 → 세트 순으로 지우고, story 초안의 이 행을 지운 뒤 그 뒤 행을 −1 한다(PK 가
아니라 레인·channel·slot 으로 찾는다 — 초안 upsert 가 섹션을 통째로 교체해 PK 가 바뀌어 있을 수 있다). 그 사이
운영자가 게시한 새 버전(이 행 포함)은 남는다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 기대 슬롯 집합과 문안은 여기 리터럴로 둔다. 테스트
(`tests/test_situation_notes_prompt_migration.py`)가 이 모듈을 `importlib` 로 불러 순수 함수와 `_patch_draft`·
`_delete_draft_row` 를 직접 부른다.
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2417f5829bb1'
down_revision: str | Sequence[str] | None = '470a2fc86186'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


prompt_sets_table = sa.table(
    "prompt_sets",
    sa.column("id", sa.Uuid()),
    sa.column("version", sa.Text()),
    sa.column("status", sa.Text()),
    sa.column("lane", sa.Text()),
    sa.column("user_label", sa.Text()),
    sa.column("story_assistant_label", sa.Text()),
    sa.column("story_example_label", sa.Text()),
    sa.column("character_assistant_label", sa.Text()),
    sa.column("note", sa.Text()),
    sa.column("published_at", sa.DateTime(timezone=True)),
)

prompt_sections_table = sa.table(
    "prompt_sections",
    sa.column("id", sa.Uuid()),
    sa.column("prompt_set_id", sa.Uuid()),
    sa.column("channel", sa.Text()),
    sa.column("scope", sa.Text()),
    sa.column("slot", sa.Text()),
    sa.column("variant", sa.Text()),
    sa.column("body", sa.Text()),
    sa.column("conditional", sa.Boolean()),
    sa.column("order", sa.Integer()),
)

# 리터럴 UUID — 작성 시점에 uuid.uuid4()를 한 번씩 실행해 뽑았다.
NEW_SET_ID = uuid.UUID('15c9e1ad-37fd-41bc-9a76-7b11131999cc')
_SECTION_ID_NAMESPACE = uuid.UUID('935d465f-03c6-4903-896f-89ac923214d6')

_LANE = "story"
_CHANNEL = "generation"
_SLOT = "situation_notes"
_ANCHOR_SLOT = "keyword_notes"

# 적용된 뒤에는 DB에 영구히 남는 값이라 문서명·번호를 넣지 않는다.
_NOTE = "상황 노트 섹션 추가"

# ---- 문안 ----------------------------------------------------------------------------------
SITUATION_NOTES_BODY = (
    "[현재 상황]\n"
    "아래는 지금 이야기 세계에서 사실인 상황이다. 이번 장면은 이 사실과 어긋나지 않게 쓴다.\n"
    "{situation_note_lines}"
)

# 이 리비전 **이전**의 story generation `(scope, slot, variant)` 기대 집합. `admin/prompts.py` 의
# `_EXPECTED_ROWS_BY_LANE` 에서 이 슬롯을 뺀 것과 같다 — 앱 코드를 import 하지 않으므로 여기 다시 적는다.
_EXPECTED_GENERATION_BEFORE: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("story", "base_content", ""),
        ("story", "base_content", "custom"),
        ("story", "rules", ""),
        ("story", "user_goal", ""),
        ("story", "development_examples", ""),
        ("story", "prologue", ""),
        ("both", "user_persona", ""),
        ("both", "memory_note", ""),
        ("both", "memory_summary", ""),
        ("both", "history", ""),
        ("story", "keyword_notes", ""),
        ("story", "shortcut_prompt", ""),
        ("both", "final_frame", ""),
    }
)

# `load_active_prompt_set`(chat/prompt_builder.py)과 같은 규칙이다.
_ACTIVE_SET_SQL = sa.text(
    "SELECT id, user_label, story_assistant_label, story_example_label, character_assistant_label,"
    " published_at"
    " FROM prompt_sets WHERE status = 'published' AND lane = :lane"
    " ORDER BY published_at DESC LIMIT 1"
)
_SECTIONS_SQL = sa.text(
    'SELECT channel, scope, slot, variant, body, conditional, "order"'
    " FROM prompt_sections WHERE prompt_set_id = :id"
)


def _assert_layout(rows: Sequence[tuple[str, str, str, str, int]]) -> int:
    """story 세트 한 벌의 배치 가정을 검사하고 기준 `K`(`keyword_notes` 의 현재 order)를 돌려준다.

    `rows` 는 `(channel, scope, slot, variant, order)` 목록이다. generation 슬롯 집합이 이 리비전 이전 기대와
    다르면(이 행이 이미 있는 경우 포함) 실제 배치를 담은 `RuntimeError` 다(배포를 멈춘다)."""
    generation = [(scope, slot, variant, order) for channel, scope, slot, variant, order in rows if channel == _CHANNEL]
    actual = {(scope, slot, variant) for scope, slot, variant, _ in generation}
    if actual != _EXPECTED_GENERATION_BEFORE or len(generation) != len(_EXPECTED_GENERATION_BEFORE):
        layout = ", ".join(
            f"{slot}{'/' + variant if variant else ''}({scope})={order}"
            for order, scope, slot, variant in sorted((o, s, sl, v) for s, sl, v, o in generation)
        )
        raise RuntimeError(
            f"[{_LANE}] {_CHANNEL} 슬롯 집합이 이 리비전 이전 기대 집합과 다르다 — "
            f"누락 {sorted(_EXPECTED_GENERATION_BEFORE - actual)}, "
            f"잉여 {sorted(actual - _EXPECTED_GENERATION_BEFORE)}: {layout}"
        )
    return next(order for _, slot, _, order in generation if slot == _ANCHOR_SLOT)


def _new_row(anchor_order: int) -> tuple[str, str, str, str, str, bool, int]:
    """더할 행 `(channel, scope, slot, variant, body, conditional, order)`."""
    return (_CHANNEL, "story", _SLOT, "", SITUATION_NOTES_BODY, True, anchor_order + 1)


def _section_id(prefix: str, channel: str, scope: str, slot: str, variant: str) -> uuid.UUID:
    return uuid.uuid5(_SECTION_ID_NAMESPACE, f"{prefix}{_LANE}:{channel}:{scope}:{slot}:{variant}")


def _build_published_rows(
    source_rows: Sequence[tuple[str, str, str, str, str, bool, int]], set_id: uuid.UUID, anchor_order: int
) -> list[dict[str, object]]:
    """원본 섹션 전부를 새 세트로 복사한 행 목록 + 새 행.

    `source_rows` 는 `(channel, scope, slot, variant, body, conditional, order)` 목록이다. body·conditional·
    variant·scope 는 바이트 그대로 두고, generation 의 `order > K` 만 +1 한다."""
    copied = [
        (
            channel,
            scope,
            slot,
            variant,
            body,
            conditional,
            order + 1 if channel == _CHANNEL and order > anchor_order else order,
        )
        for channel, scope, slot, variant, body, conditional, order in source_rows
    ]
    return [
        {
            "id": _section_id("", channel, scope, slot, variant),
            "prompt_set_id": set_id,
            "channel": channel,
            "scope": scope,
            "slot": slot,
            "variant": variant,
            "body": body,
            "conditional": conditional,
            "order": order,
        }
        for channel, scope, slot, variant, body, conditional, order in [*copied, _new_row(anchor_order)]
    ]


def _patch_draft(conn: Connection) -> bool:
    """story 레인에 초안이 없으면 `False`. 있으면 초안 **자신의** 배치로 가정을 검사한 뒤 generation 의 `order > K`
    행을 +1 하고(body 불변) 새 행을 넣고 `True`. 초안은 레인당 1개라(`ix_prompt_sets_draft`) 새 세트를 만들지 않고
    제자리에서 고친다.

    `op` 를 쓰지 않는다 — 테스트가 롤백되는 세션의 커넥션에 `run_sync` 로 부르기 위해서다."""
    draft_id = conn.execute(
        sa.text("SELECT id FROM prompt_sets WHERE status = 'draft' AND lane = :lane"), {"lane": _LANE}
    ).scalar_one_or_none()
    if draft_id is None:
        return False

    rows = conn.execute(_SECTIONS_SQL, {"id": draft_id}).fetchall()
    anchor_order = _assert_layout(
        [(channel, scope, slot, variant, order) for channel, scope, slot, variant, _body, _cond, order in rows]
    )
    conn.execute(
        sa.text(
            'UPDATE prompt_sections SET "order" = "order" + 1'
            ' WHERE prompt_set_id = :id AND channel = :channel AND "order" > :k'
        ),
        {"id": draft_id, "channel": _CHANNEL, "k": anchor_order},
    )
    channel, scope, slot, variant, body, conditional, order = _new_row(anchor_order)
    conn.execute(
        sa.insert(prompt_sections_table),
        [
            {
                "id": _section_id("draft:", channel, scope, slot, variant),
                "prompt_set_id": draft_id,
                "channel": channel,
                "scope": scope,
                "slot": slot,
                "variant": variant,
                "body": body,
                "conditional": conditional,
                "order": order,
            }
        ],
    )
    return True


def _delete_draft_row(conn: Connection) -> None:
    """story 초안의 이 행을 지우고 그 뒤 generation 행을 −1 한다. character 레인(초안 포함)은 건드리지 않는다."""
    found = conn.execute(
        sa.text(
            'SELECT s.id, s.prompt_set_id, s."order" FROM prompt_sections s'
            " JOIN prompt_sets p ON p.id = s.prompt_set_id"
            " WHERE p.status = 'draft' AND p.lane = :lane AND s.channel = :channel AND s.slot = :slot"
        ),
        {"lane": _LANE, "channel": _CHANNEL, "slot": _SLOT},
    ).fetchall()
    for section_id, prompt_set_id, order in found:
        conn.execute(sa.text("DELETE FROM prompt_sections WHERE id = :id"), {"id": section_id})
        conn.execute(
            sa.text(
                'UPDATE prompt_sections SET "order" = "order" - 1'
                ' WHERE prompt_set_id = :set_id AND channel = :channel AND "order" > :x'
            ),
            {"set_id": prompt_set_id, "channel": _CHANNEL, "x": order},
        )


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    source = bind.execute(_ACTIVE_SET_SQL, {"lane": _LANE}).one()
    rows = bind.execute(_SECTIONS_SQL, {"id": source.id}).fetchall()
    anchor_order = _assert_layout(
        [(channel, scope, slot, variant, order) for channel, scope, slot, variant, _b, _c, order in rows]
    )

    # `_next_published_version`(admin/prompts.py)과 같은 규칙 — 전 레인 대상.
    latest_version = bind.execute(
        sa.text("SELECT max(CAST(version AS INTEGER)) FROM prompt_sets WHERE status = 'published'")
    ).scalar_one()
    op.bulk_insert(
        prompt_sets_table,
        [
            {
                "id": NEW_SET_ID,
                "version": str((latest_version or 0) + 1),
                "status": "published",
                "lane": _LANE,
                "user_label": source.user_label,
                "story_assistant_label": source.story_assistant_label,
                "story_example_label": source.story_example_label,
                "character_assistant_label": source.character_assistant_label,
                "note": _NOTE,
                # SQL now()가 아니다 — 위 docstring.
                "published_at": max(datetime.now(UTC), source.published_at + timedelta(seconds=1)),
            }
        ],
    )
    op.bulk_insert(prompt_sections_table, _build_published_rows([tuple(row) for row in rows], NEW_SET_ID, anchor_order))

    chosen = bind.execute(_ACTIVE_SET_SQL, {"lane": _LANE}).one().id
    if chosen != NEW_SET_ID:
        raise RuntimeError(f"[{_LANE}] 새 세트가 활성으로 뽑히지 않는다: 활성={chosen}, 새 세트={NEW_SET_ID}")

    _patch_draft(bind)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(sa.delete(prompt_sections_table).where(prompt_sections_table.c.prompt_set_id == NEW_SET_ID))
    op.execute(sa.delete(prompt_sets_table).where(prompt_sets_table.c.id == NEW_SET_ID))
    _delete_draft_row(op.get_bind())
