"""prompt sections story media judgment

Revision ID: 2519dde454e0
Revises: 9f7578617781
Create Date: 2026-10-01 12:00:00.000000

스토리 대화 중 미디어 북 칸 하나를 골라 응답 아래에 붙이는 판정 지시문을 story 레인 프롬프트 세트에
넣는다. 캐릭터 상황별 이미지 판정과 같은 channel `image_judgment` 의 3행(`image_list_intro`·
`turn_context`·`judgment_instruction`)을 scope `story` 로 더한다. story 레인에는 이 channel 이 없었으므로
기준 행이 없고 order 는 1·2·3 고정이다. 레인에 새 channel 을 더한 `c328445d4c2d`, 세트 복사·초안 패치를
처음 쓴 `b72c33c70240` 과 같은 모양이다.

**기존 published 세트는 건드리지 않는다.** story 레인의 활성 세트를 복사한 **새 published 세트**를 만들고
행을 더한다. 다른 행은 body·conditional·order 까지 바이트 그대로라 칸 판정 밖의 렌더는 이 리비전 전과 같다.

**모든 쿼리는 story 레인으로 한정한다.** character 레인에도 같은 channel(캐릭터 상황별 이미지 판정)이
있다. 가드·삽입·초안 패치·되돌리기가 channel 만 보고 움직이면 character 레인의 행을 건드린다 — 특히
되돌리기에서 초안 행을 channel 로만 지우면 character 초안의 판정 행이 사라진다.

**가정이 어긋나면 배포를 멈춘다**(`_assert_layout`): story 세트(활성·초안 각자)에 `image_judgment` 행이
이미 있으면 `RuntimeError`. 체인이 한 트랜잭션이라(`migrations/env.py` `do_run_migrations`) 앞 스키마
리비전도 함께 롤백된다.

**`published_at` 은 SQL `now()` 가 아니라 파이썬 `max(now, 원본 + 1초)` 다** — 체인이 한 트랜잭션이라 SQL
`now()` 는 체인 시작 시각이어서, 원본이 같은 체인에서 만들어진 DB(테스트 DB)에서는 새 세트가 원본보다
과거가 될 수 있다. 삽입 뒤 활성 SELECT 를 다시 돌려 새 세트가 뽑히는지 확인한다.

**초안**: story 레인에 초안이 있으면 초안에도 같은 3행을 제자리에서 넣는다(`_patch_draft`). 다른 행은
건드리지 않는다. 운영에는 story 초안이 실제로 있다.

**PK**: 새 세트는 리터럴 UUID(`NEW_SET_ID`). 섹션은 `uuid5(_SECTION_ID_NAMESPACE,
"story:{channel}:{scope}:{slot}:{variant}")`, 초안 행은 `draft:` 접두사를 붙인다(`uuid4()` 호출 금지 규약).

**문안**은 이 파일의 `*_BODY` 상수가 유일한 소스다. 캐릭터 레인의 같은 슬롯 문안을 칸(인물·장면)에 맞게
고친 초안이다.

⚠️ **운영 메모**:
- 마이그레이션은 활성 세트 캐시를 지우지 않는다 — 배포 직후 최대 300초(`prompt_set_cache_ttl_seconds`)
  동안 story 레인은 이 channel 이 없는 옛 세트로 렌더한다. 그때 칸 판정 프롬프트는 빈 문자열이 되고,
  판정 조립 함수가 그것을 렌더 실패로 올려 그 턴은 그림 없이 진행한다(빈 프롬프트로 판정을 부르지 않는다).
- 배포 전부터 열어 둔 어드민 프롬프트 편집 탭에서 저장하면 초안이 섹션 전체 교체로 새 행을 잃고 게시가
  슬롯 집합 검사("누락")로 막힌다. **배포 뒤에는 편집 탭을 새로고침한다.**
- **이 리비전 이전 story 버전은 복원해도 게시할 수 없다**(슬롯 집합 검사 "누락", 제약으로 받아들임).

**롤백**: 1순위는 태그 롤백(이미지만 되돌리고 스키마·세트는 그대로)이다. 옛 코드는 story 레인에서 이
channel 을 렌더하지 않으므로 새 행은 쓰이지 않는다. 다만 옛 코드의 슬롯 집합 검사가 새 세트를 "잉여"로
거부해 **story 레인 어드민 게시만** 막힌다 — 그 상태에서 게시가 필요하면 이 리비전 이전 버전을 복원해서
게시한다.

`downgrade()`: 리터럴 세트의 섹션 → 세트 순으로 지우고, story 초안의 이 channel 행을 지운다(PK 가 아니라
레인·channel 로 찾는다 — 초안 upsert 가 섹션을 통째로 교체해 PK 가 바뀌어 있을 수 있다). channel 전체가
빠지므로 다른 행의 order 를 당길 필요가 없다. 그 사이 운영자가 게시한 새 버전(이 행 포함)은 남는다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 테스트(`tests/test_media_judgment_prompt_migration.py`)가
이 모듈을 `importlib` 로 불러 순수 함수와 `_patch_draft`·`_delete_draft_rows` 를 직접 부른다.
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2519dde454e0'
down_revision: str | Sequence[str] | None = '9f7578617781'
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
NEW_SET_ID = uuid.UUID('54aedfca-8267-43f5-a824-499d9eb8cb1c')
_SECTION_ID_NAMESPACE = uuid.UUID('35790dcb-de02-45a1-a546-8968a52e3a95')

_LANE = "story"
_CHANNEL = "image_judgment"

# 적용된 뒤에는 DB에 영구히 남는 값이라 문서명·번호를 넣지 않는다.
_NOTE = "스토리 미디어 북 칸 판정 채널 추가"

# ---- 문안 ----------------------------------------------------------------------------------
# 판정 근거는 칸의 인물·장면 이름과(있으면) 상황 설명이다 — 후보 줄은 코드(`media_cell_image_lines`)가
# 만든다. 목록 순서는 빌더의 축 순서(인물 → 장면)일 뿐 우선순위가 아니라서, 캐릭터 문안과 달리 "목록에서 앞의
# 것"으로 고르게 하지 않고 이번 턴과 가장 구체적으로 맞는 칸을 고르게 한다.
IMAGE_LIST_INTRO_BODY = (
    "다음은 이 스토리의 미디어 북에 등록된 칸(인물·장면) 목록이다.\n"
    "{image_lines}"
)
TURN_CONTEXT_BODY = "[대화 기록]\n{turn_lines}"
JUDGMENT_INSTRUCTION_BODY = (
    "위 대화, 특히 마지막 사용자 행동과 그에 대한 진행자의 응답을 근거로 이번 턴의 장면에 맞는 칸이 있는지 "
    "판단하라. 칸이 맞는지는 인물·장면 이름과, 있으면 상황 설명으로 판단한다. 여러 칸이 동시에 맞으면 상황 설명이 "
    "이번 턴과 가장 구체적으로 맞는 칸 하나만 선택하라. 맞는 칸이 없으면 matchedImageEntityId를 null로 응답하라."
)

# `(channel, scope, slot, variant, body, conditional, order)` — 새 channel 은 기준 행이 없어 order 가 고정이다.
NEW_ROWS: tuple[tuple[str, str, str, str, str, bool, int], ...] = (
    (_CHANNEL, "story", "image_list_intro", "", IMAGE_LIST_INTRO_BODY, False, 1),
    (_CHANNEL, "story", "turn_context", "", TURN_CONTEXT_BODY, False, 2),
    (_CHANNEL, "story", "judgment_instruction", "", JUDGMENT_INSTRUCTION_BODY, False, 3),
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


def _assert_layout(channels: Sequence[str]) -> None:
    """`channels` 는 story 세트 한 벌의 행 channel 목록이다. 이 channel 행이 이미 있으면 두 번 적용되는
    것이라 `RuntimeError`(배포를 멈춘다)."""
    existing = sum(1 for channel in channels if channel == _CHANNEL)
    if existing:
        raise RuntimeError(f"[{_LANE}] {_CHANNEL} channel 행이 이미 {existing}개 있다")


def _section_id(prefix: str, channel: str, scope: str, slot: str, variant: str) -> uuid.UUID:
    return uuid.uuid5(_SECTION_ID_NAMESPACE, f"{prefix}{_LANE}:{channel}:{scope}:{slot}:{variant}")


def _build_published_rows(
    source_rows: Sequence[tuple[str, str, str, str, str, bool, int]], set_id: uuid.UUID
) -> list[dict[str, object]]:
    """원본 섹션 전부를 바이트 그대로 새 세트로 복사한 행 목록 + 새 channel 3행.

    `source_rows` 는 `(channel, scope, slot, variant, body, conditional, order)` 목록이다."""
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
        for channel, scope, slot, variant, body, conditional, order in [*source_rows, *NEW_ROWS]
    ]


def _patch_draft(conn: Connection) -> bool:
    """story 레인에 초안이 없으면 `False`. 있으면 초안 **자신의** 행으로 가정을 검사한 뒤 새 3행을 제자리에서
    넣고 `True`. 초안은 레인당 1개라(`ix_prompt_sets_draft`) 새 세트를 만들지 않는다.

    `op` 를 쓰지 않는다 — 테스트가 롤백되는 세션의 커넥션에 `run_sync` 로 부르기 위해서다."""
    draft_id = conn.execute(
        sa.text("SELECT id FROM prompt_sets WHERE status = 'draft' AND lane = :lane"), {"lane": _LANE}
    ).scalar_one_or_none()
    if draft_id is None:
        return False

    rows = conn.execute(_SECTIONS_SQL, {"id": draft_id}).fetchall()
    _assert_layout([row.channel for row in rows])
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
            for channel, scope, slot, variant, body, conditional, order in NEW_ROWS
        ],
    )
    return True


def _delete_draft_rows(conn: Connection) -> None:
    """story 초안의 이 channel 행만 지운다. character 레인(초안 포함)의 같은 channel 행은 캐릭터 상황별 이미지
    판정이라 남겨야 한다."""
    conn.execute(
        sa.text(
            "DELETE FROM prompt_sections s USING prompt_sets p"
            " WHERE p.id = s.prompt_set_id AND p.status = 'draft' AND p.lane = :lane AND s.channel = :channel"
        ),
        {"lane": _LANE, "channel": _CHANNEL},
    )


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    source = bind.execute(_ACTIVE_SET_SQL, {"lane": _LANE}).one()
    rows = bind.execute(_SECTIONS_SQL, {"id": source.id}).fetchall()
    _assert_layout([row.channel for row in rows])

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
    op.bulk_insert(prompt_sections_table, _build_published_rows([tuple(row) for row in rows], NEW_SET_ID))

    chosen = bind.execute(_ACTIVE_SET_SQL, {"lane": _LANE}).one().id
    if chosen != NEW_SET_ID:
        raise RuntimeError(f"[{_LANE}] 새 세트가 활성으로 뽑히지 않는다: 활성={chosen}, 새 세트={NEW_SET_ID}")

    _patch_draft(bind)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(sa.delete(prompt_sections_table).where(prompt_sections_table.c.prompt_set_id == NEW_SET_ID))
    op.execute(sa.delete(prompt_sets_table).where(prompt_sets_table.c.id == NEW_SET_ID))
    _delete_draft_rows(op.get_bind())
