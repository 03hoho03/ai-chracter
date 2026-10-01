"""prompt sections publish filter media book

Revision ID: bd29dd69bc0f
Revises: 2519dde454e0
Create Date: 2026-10-01 18:00:00.000000

스토리 발행 심사 프롬프트에 미디어 북 칸 줄(`- 인물/장면: 상황 설명 (해금 힌트: …)`)을 싣는 슬롯을 publish_filter 레인
프롬프트 세트에 넣는다. publish_filter channel 에 `media_book` 1행(scope `story`, `conditional=True`)을
`starting_setups` 뒤·`verdict_instruction` 앞에 더한다. 칸 그림(축소본)은 같은 심사 호출에 이미지로 실리고, 이
행이 그 그림과 줄이 짝이라는 것과 칸 이름·상황 설명·해금 힌트도 심사하라는 것을 알린다. 기존 channel 에 슬롯 하나를 더한
`b72c33c70240` 과 같은 모양이다.

**기존 published 세트는 건드리지 않는다.** publish_filter 레인의 활성 세트를 복사한 **새 published 세트**를
만들고 행을 더한다. 다른 행은 body·conditional·scope·variant 까지 바이트 그대로이고 order 만 아래 규칙으로
민다. 새 행이 `conditional=True` 라 미디어 북이 없는 스토리(값이 빈 문자열)는 이 섹션째 빠져 심사 프롬프트가
이 리비전 전과 같다. scope `story` 라 캐릭터 심사에는 들어가지 않는다.

**삽입 자리는 절대 order 가 아니라 `verdict_instruction` 의 지금 order(`V`)다** — 운영자가 어드민에서 order 를
바꿀 수 있다. 새 행이 `V` 를 갖고 publish_filter channel 에서 `order >= V` 인 행은 scope 와 무관하게 +1 한다.

**가정이 어긋나면 배포를 멈춘다**(`_assert_layout`): publish_filter channel 의 `(scope, slot, variant)` 집합이
이 리비전 이전 16행과 정확히 같지 않거나, `media_book` 행이 이미 있거나, `starting_setups` 가
`verdict_instruction` 앞에 있지 않으면(둘 사이에 넣는다는 자리를 만족할 수 없다) `RuntimeError`. 체인이 한
트랜잭션이라(`migrations/env.py` `do_run_migrations`) 앞 스키마 리비전도 함께 롤백된다.

**모든 쿼리는 publish_filter 레인으로 한정한다** — 활성 세트 조회·초안 조회·되돌리기 삭제 모두 `lane` 조건을
건다. 초안은 레인마다 하나라 레인 조건이 빠지면 다른 레인의 초안을 집는다.

**`published_at` 은 SQL `now()` 가 아니라 파이썬 `max(now, 원본 + 1초)` 다** — 체인이 한 트랜잭션이라 SQL
`now()` 는 체인 시작 시각이어서, 원본이 같은 체인에서 만들어진 DB(테스트 DB)에서는 새 세트가 원본보다
과거가 될 수 있다. 삽입 뒤 활성 SELECT 를 다시 돌려 새 세트가 뽑히는지 확인한다.

**초안**: publish_filter 레인에 초안이 있으면 초안 **자신의** 배치로 가정을 검사한 뒤 제자리에서 같은 규칙으로
order 를 밀고 행을 넣는다(`_patch_draft`).

**PK**: 새 세트는 리터럴 UUID(`NEW_SET_ID`). 섹션은 `uuid5(_SECTION_ID_NAMESPACE,
"publish_filter:{channel}:{scope}:{slot}:{variant}")`, 초안 행은 `draft:` 접두사를 붙인다(`uuid4()` 호출 금지 규약).

**문안**은 이 파일의 `MEDIA_BOOK_BODY` 상수가 유일한 소스다. 기존 publish_filter 문안의 톤(`[제목]` 줄 + 값)을
따른 초안이다.

⚠️ **운영 메모**:
- 마이그레이션은 활성 세트 캐시를 지우지 않는다 — 배포 직후 최대 300초(`prompt_set_cache_ttl_seconds`)
  동안 publish_filter 레인은 이 행이 없는 옛 세트로 렌더한다. 그동안의 발행 심사는 칸 그림은 받지만 칸 줄과
  그 설명 문장이 빠진다(값이 들어갈 섹션이 없어 렌더 오류는 나지 않는다).
- 배포 전부터 열어 둔 어드민 프롬프트 편집 탭에서 저장하면 초안이 섹션 전체 교체로 새 행을 잃고 게시가
  슬롯 집합 검사("누락")로 막힌다. **배포 뒤에는 편집 탭을 새로고침한다.**
- **이 리비전 이전 publish_filter 버전은 복원해도 게시할 수 없다**(슬롯 집합 검사 "누락", 제약으로 받아들임).

**롤백**: 1순위는 태그 롤백(이미지만 되돌리고 스키마·세트는 그대로)이다. 옛 코드는 이 슬롯의 값을 넘기지
않으므로(`conditional` — 값이 없으면 빠진다) 새 행은 렌더에 나오지 않는다. 다만 옛 코드의 슬롯 집합 검사가
새 세트를 "잉여"로 거부해 **publish_filter 레인 어드민 게시만** 막힌다 — 그 상태에서 게시가 필요하면 이
리비전 이전 버전을 복원해서 게시한다.

`downgrade()`: 리터럴 세트의 섹션 → 세트 순으로 지우고, publish_filter 초안의 `media_book` 행을 PK 가 아니라
레인·슬롯으로 찾아(초안 upsert 가 섹션을 통째로 교체해 PK 가 바뀌어 있을 수 있다) 그 order `X` 를 읽고 지운 뒤
`order > X` 인 publish_filter channel 행을 −1 한다. 그 사이 운영자가 게시한 새 버전(이 행 포함)은 남는다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 테스트(`tests/test_media_book_filter_prompt_migration.py`)가
이 모듈을 `importlib` 로 불러 순수 함수와 `_patch_draft`·`_delete_draft_rows` 를 직접 부른다.
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'bd29dd69bc0f'
down_revision: str | Sequence[str] | None = '2519dde454e0'
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
NEW_SET_ID = uuid.UUID('b320a7ba-8114-462e-b719-dacf46bd9b53')
_SECTION_ID_NAMESPACE = uuid.UUID('4cb6d289-9aef-4af5-8c1b-87bf283dea9e')

_LANE = "publish_filter"
_CHANNEL = "publish_filter"
_SLOT = "media_book"
_SCOPE = "story"

# 적용된 뒤에는 DB에 영구히 남는 값이라 문서명·번호를 넣지 않는다.
_NOTE = "스토리 발행 심사에 미디어 북 칸 슬롯 추가"

# ---- 문안 ----------------------------------------------------------------------------------
# 줄은 코드가 만든다(`build_story_publish_filter_prompt` — 칸마다 `- 인물/장면: 상황 설명 (해금 힌트: …)`, 빈 부분은
# 뺀다). 해금 힌트는 보관함에서 다른 플레이어에게 보이는 글이라 함께 심사한다.
# 마지막 문장은 심사 범위를 긋는다 — 칸 그림이 스토리 내용과 맞지 않는다는 이유로 거부한 실측이 있었다. 작가가
# 어떤 그림을 칸에 거는지는 작가의 선택이고, 심사는 부적절한 내용만 거른다.
# 칸 그림은 대표 이미지 뒤에 같은 순서로 실린다. `{media_book_lines}` 가 빠지면 이 섹션은 미디어 북이 없는
# 스토리에서도 드롭되지 않는다.
MEDIA_BOOK_BODY = (
    "[미디어 북]\n"
    "대표 이미지 뒤에 첨부된 이미지들은 아래 칸의 그림이며 순서가 같다. "
    "각 줄은 \"인물/장면: 상황 설명 (해금 힌트: …)\"이고, 상황 설명이나 해금 힌트가 없는 칸은 그 부분이 빠져 있다. "
    "그림과 함께 이름·상황 설명·해금 힌트도 심사하라. "
    "그림과 스토리가 어울리는지는 심사 대상이 아니다 — 맨 위에 적은 기준(선정성/폭력성/혐오 표현/불법 콘텐츠 등 "
    "서비스에 부적절한 내용)에 해당하는지만 본다.\n"
    "{media_book_lines}"
)

# 이 리비전 **이전**의 publish_filter channel `(scope, slot, variant)` 기대 집합. `admin/prompts.py` 의
# `_EXPECTED_ROWS_BY_LANE["publish_filter"]` 에서 `media_book` 을 뺀 것과 같다 — 앱 코드를 import 하지 않으므로
# 여기 다시 적는다. 게시 검증이 이 집합을 고정하고 어드민 UI 로는 행을 더하거나 뺄 수 없다.
_EXPECTED_BEFORE: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("character", "intro_instruction", ""),
        ("story", "intro_instruction", ""),
        ("both", "name", ""),
        ("both", "one_liner", ""),
        ("character", "intro", ""),
        ("story", "setting_text", ""),
        ("story", "development_example_legacy", ""),
        ("story", "custom_prompt", ""),
        ("story", "rules", ""),
        ("story", "user_goal", ""),
        ("story", "development_examples_pairs", ""),
        ("character", "example_dialogues", ""),
        ("character", "character_prompt", ""),
        ("both", "detail_description", ""),
        ("story", "starting_setups", ""),
        ("both", "verdict_instruction", ""),
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
    """이 리비전이 기대는 배치를 검사하고 삽입 order `V`(= `verdict_instruction` 의 지금 order)를 돌려준다.

    `rows` 는 publish_filter 세트 한 벌의 `(channel, scope, slot, variant, order)` 목록이다. 어긋나면 실제 배치를
    담은 `RuntimeError` 다(배포를 멈춘다)."""
    channel_rows = sorted(
        (order, scope, slot, variant) for channel, scope, slot, variant, order in rows if channel == _CHANNEL
    )
    layout = ", ".join(f"{slot}({scope})={order}" for order, scope, slot, _ in channel_rows)

    if any(slot == _SLOT for _, _, slot, _ in channel_rows):
        raise RuntimeError(f"[{_LANE}] {_SLOT} 행이 이미 있다: {layout}")

    actual = {(scope, slot, variant) for _, scope, slot, variant in channel_rows}
    if actual != _EXPECTED_BEFORE or len(channel_rows) != len(_EXPECTED_BEFORE):
        raise RuntimeError(
            f"[{_LANE}] 슬롯 집합이 이 리비전 이전 기대와 다르다 — "
            f"누락 {sorted(_EXPECTED_BEFORE - actual)}, 잉여 {sorted(actual - _EXPECTED_BEFORE)}: {layout}"
        )

    orders = {slot: order for order, _, slot, _ in channel_rows}
    insert_order = orders["verdict_instruction"]
    if not orders["starting_setups"] < insert_order:
        raise RuntimeError(
            f"[{_LANE}] starting_setups(order={orders['starting_setups']})가 verdict_instruction"
            f"(order={insert_order}) 앞에 있지 않다 — 둘 사이에 넣을 수 없다: {layout}"
        )
    return insert_order


def _section_id(prefix: str, channel: str, scope: str, slot: str, variant: str) -> uuid.UUID:
    return uuid.uuid5(_SECTION_ID_NAMESPACE, f"{prefix}{_LANE}:{channel}:{scope}:{slot}:{variant}")


def _build_published_rows(
    source_rows: Sequence[tuple[str, str, str, str, str, bool, int]], set_id: uuid.UUID, insert_order: int
) -> list[dict[str, object]]:
    """원본 섹션 전부를 새 세트로 복사한 행 목록 + `media_book` 행 하나.

    `source_rows` 는 `(channel, scope, slot, variant, body, conditional, order)` 목록이다. body·conditional·
    scope·variant 는 바이트 그대로 두고, publish_filter channel 에서 `order >= insert_order` 인 행만 +1 한다.
    그래서 `insert_order` 에는 새 행 하나만 남는다(같은 order 를 나눠 쓰는 scope 짝은 함께 밀린다)."""
    built: list[dict[str, object]] = [
        {
            "id": _section_id("", channel, scope, slot, variant),
            "prompt_set_id": set_id,
            "channel": channel,
            "scope": scope,
            "slot": slot,
            "variant": variant,
            "body": body,
            "conditional": conditional,
            "order": order + 1 if channel == _CHANNEL and order >= insert_order else order,
        }
        for channel, scope, slot, variant, body, conditional, order in source_rows
    ]
    built.append(
        {
            "id": _section_id("", _CHANNEL, _SCOPE, _SLOT, ""),
            "prompt_set_id": set_id,
            "channel": _CHANNEL,
            "scope": _SCOPE,
            "slot": _SLOT,
            "variant": "",
            "body": MEDIA_BOOK_BODY,
            "conditional": True,
            "order": insert_order,
        }
    )
    return built


def _patch_draft(conn: Connection) -> bool:
    """publish_filter 레인에 초안이 없으면 `False`. 있으면 초안 **자신의** 배치로 가정을 검사한 뒤(초안의 `V` 는
    활성 세트와 다를 수 있다) 기존 행은 order 만 민다(`order >= V` +1, body 불변). 그다음 `media_book` 행을 order
    `V` 로 더하고 `True` 를 돌려준다. 초안은 레인당 1개라(`ix_prompt_sets_draft`) 새 세트를 만들지 않는다.

    `op` 를 쓰지 않는다 — 테스트가 롤백되는 세션의 커넥션에 `run_sync` 로 부르기 위해서다."""
    draft_id = conn.execute(
        sa.text("SELECT id FROM prompt_sets WHERE status = 'draft' AND lane = :lane"), {"lane": _LANE}
    ).scalar_one_or_none()
    if draft_id is None:
        return False

    rows = conn.execute(_SECTIONS_SQL, {"id": draft_id}).fetchall()
    insert_order = _assert_layout(
        [(channel, scope, slot, variant, order) for channel, scope, slot, variant, _body, _cond, order in rows]
    )
    conn.execute(
        sa.text(
            'UPDATE prompt_sections SET "order" = "order" + 1'
            ' WHERE prompt_set_id = :id AND channel = :channel AND "order" >= :v'
        ),
        {"id": draft_id, "channel": _CHANNEL, "v": insert_order},
    )
    conn.execute(
        sa.insert(prompt_sections_table).values(
            id=_section_id("draft:", _CHANNEL, _SCOPE, _SLOT, ""),
            prompt_set_id=draft_id,
            channel=_CHANNEL,
            scope=_SCOPE,
            slot=_SLOT,
            variant="",
            body=MEDIA_BOOK_BODY,
            conditional=True,
            order=insert_order,
        )
    )
    return True


def _delete_draft_rows(conn: Connection) -> None:
    """publish_filter 초안의 `media_book` 행을 지우고 그 뒤 행의 order 를 하나씩 당긴다."""
    draft_rows = conn.execute(
        sa.text(
            'SELECT s.id, s.prompt_set_id, s."order" FROM prompt_sections s'
            " JOIN prompt_sets p ON p.id = s.prompt_set_id"
            " WHERE p.status = 'draft' AND p.lane = :lane AND s.channel = :channel AND s.slot = :slot"
        ),
        {"lane": _LANE, "channel": _CHANNEL, "slot": _SLOT},
    ).fetchall()
    for section_id, prompt_set_id, order in draft_rows:
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
    insert_order = _assert_layout(
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
    op.bulk_insert(
        prompt_sections_table, _build_published_rows([tuple(row) for row in rows], NEW_SET_ID, insert_order)
    )

    chosen = bind.execute(_ACTIVE_SET_SQL, {"lane": _LANE}).one().id
    if chosen != NEW_SET_ID:
        raise RuntimeError(f"[{_LANE}] 새 세트가 활성으로 뽑히지 않는다: 활성={chosen}, 새 세트={NEW_SET_ID}")

    _patch_draft(bind)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(sa.delete(prompt_sections_table).where(prompt_sections_table.c.prompt_set_id == NEW_SET_ID))
    op.execute(sa.delete(prompt_sets_table).where(prompt_sets_table.c.id == NEW_SET_ID))
    _delete_draft_rows(op.get_bind())
