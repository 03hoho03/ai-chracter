"""prompt sections user name slot

Revision ID: 8e895c898730
Revises: 85df98c44368
Create Date: 2026-10-04 15:08:49.348031

사용자 이름 한 줄(`user_name`, conditional) 섹션을 story·character 두 레인의 프롬프트 세트에 넣는다. 작가 글의
`{{user}}` 가 이름으로 바뀌어 프롬프트에 들어가므로, 판정·요약 모델이 대화 속 그 이름이 사용자라는 걸 알게 하는 줄이다.

- 판정·요약 채널(story: stat_judgment·ending_judgment·image_judgment·memory_summary, character: image_judgment·
  memory_summary): 실제 이름(대화 프로필 이름 또는 작품 기본 이름)이 있을 때만 값이 있다.
- generation 채널(두 레인): 프로필이 없고 작품 기본 이름이 있을 때만 값이 있다. 프로필이 있으면 `user_persona` 섹션이
  이미 이름을 준다. 작품 기본 이름으로 `user_persona` 를 채우지 않는 이유는 그 섹션 문안이 "사용자가 스스로 정한 자기
  설정"이라 작가가 정한 이름에는 거짓 문장이 되기 때문이다.

값이 비면 conditional 섹션째 드롭되므로(`render_prompt_channel`) 이름이 없는 방(생성은 프로필이 있는 방도)의 프롬프트는
이 리비전 전과 바이트까지 같다. 행 수는 레인 × 실제로 있는 채널이다 — story 5(generation·stat·ending·image 판정·요약),
character 3(generation·image 판정·요약). character 레인에는 스탯·엔딩 판정 채널이 없다.

**위치**(`_PLACEMENTS`) — 이름이 대화 기록을 읽기 전에 오게 한다.
- generation: `user_persona` **바로 뒤**. 두 섹션은 같은 정보를 다른 출처로 주는 자리라 붙여 둔다(생성 채널에서는 둘 중
  하나만 실린다).
- stat_judgment·image_judgment: `turn_context`(대화 기록) **바로 앞**.
- ending_judgment: `memory_summary`(앞선 대화의 요약 — 대화 기록 묶음의 첫 섹션) **바로 앞**.
- memory_summary: `previous_summary`(요약할 재료의 첫 섹션) **바로 앞**, 즉 지시문 뒤.

**위치는 절대 order가 아니라 기준 행의 현재 order다.** 운영자는 어드민의 위·아래 버튼으로 order를 맞바꿀 수 있다.
기준 행의 현재 order 로 새 행의 자리 `X` 를 정하고(앞이면 기준 order, 뒤면 기준 order + 1), 그 채널의 `order >= X` 를
+1 한 뒤 새 행을 `X` 에 둔다. 나머지 행의 상대 순서는 그대로다.

**가정이 어긋나면 배포를 멈춘다**(`_assert_layout`). 체인이 한 트랜잭션이라(`migrations/env.py` `do_run_migrations`)
앞 스키마 리비전도 함께 롤백된다. 멈추는 경우: 다섯 채널 중 하나라도 슬롯 집합이 이 리비전 이전 기대 집합과 다름(이미
`user_name` 행이 있는 경우, character 레인에 스탯·엔딩 판정 행이 있는 경우 포함).

**`published_at`은 SQL `now()`가 아니라 파이썬 `max(now, 원본 + 1초)`다** — 체인이 한 트랜잭션이라 SQL `now()` 는 체인
시작 시각이어서, 원본이 같은 체인에서 만들어진 DB(테스트 DB)에서는 새 세트가 원본보다 과거가 될 수 있다. 삽입 뒤 활성
SELECT 를 다시 돌려 새 세트가 뽑히는지 확인한다.

**초안**: 레인에 초안이 있으면 초안에도 같은 행을 **제자리에서** 넣고 order 를 민다(`_patch_draft`). 초안 자신의 배치로
가정을 검사한다(초안의 기준 order 는 활성 세트와 다를 수 있다). 기존 행의 body 는 건드리지 않는다. 운영에는 두 레인 모두
초안이 있다.

**PK**: 새 세트 2개는 리터럴 UUID(`NEW_SET_IDS`). 섹션은 `uuid5(_SECTION_ID_NAMESPACE,
"{lane}:{channel}:{scope}:{slot}:{variant}")`, 초안 행은 `draft:` 접두사를 붙인다(`uuid4()` 호출 금지 규약).

**문안**은 이 파일의 `*_BODY` 상수가 유일한 소스다. "사용자의 이름" 이 아니라 "대화 속 사용자의 이름" 이라 쓴 것은 요약
지시문의 "사용자의 계정 정보는 쓰지 않는다" 와 부딪히지 않게 — 이 이름이 계정이 아니라 대화 속에서 사용자를 부르는
이름이라는 걸 문안이 말하게 하려는 것이다.

⚠️ **운영 메모**:
- body 에서 `{user_name}` 을 지우면 드롭 조건이 거짓이 되어 **모든 방에 머리글만 나간다**. 게시 검증은 "허용 밖 이름"만
  막고 "필수 이름의 존재"는 보지 않는다.
- 마이그레이션은 활성 세트 캐시를 지우지 않는다 — 배포 직후 최대 300초(`prompt_set_cache_ttl_seconds`) 동안 옛 세트로
  렌더한다. 그동안 이름 한 줄이 실리지 않을 뿐 렌더는 깨지지 않는다.
- 배포 전부터 열어 둔 어드민 프롬프트 편집 탭에서 저장하면 초안이 섹션 전체 교체로 새 행을 잃고 게시가 슬롯 집합 검사
  ("누락")로 막힌다. **배포 뒤에는 편집 탭을 새로고침한다.**
- **이 리비전 이전 버전은 복원해도 게시할 수 없다**(슬롯 집합 검사 "누락", 제약으로 받아들임).

**롤백**: 1순위는 태그 롤백(이미지만 되돌리고 스키마·세트는 그대로)이다. 옛 코드는 `user_name` 값을 넘기지 않으므로 새
행은 드롭되어 렌더가 깨지지 않는다. 다만 옛 코드의 슬롯 집합 검사가 새 세트를 "잉여"로 거부해 **두 레인의 어드민 게시만**
막힌다 — 그 상태에서 게시가 필요하면 이 리비전 이전 버전을 복원해서 게시한다. 옛 코드는 작가 글의 `{{user}}` 도 바꾸지
않으므로 이미 `{{user}}` 를 쓴 작품은 글자 그대로 나간다.

`downgrade()`: 리터럴 세트의 섹션 → 세트 순으로 지우고, 초안의 이 행을 지운 뒤 그 채널의 뒤 행을 −1 한다(PK 가 아니라
레인·slot 으로 찾는다 — 초안 upsert 가 섹션을 통째로 교체해 PK 가 바뀌어 있을 수 있다). 그 사이 운영자가 게시한 새
버전(이 행 포함)은 남는다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 기대 슬롯 집합과 문안은 여기 리터럴로 둔다. 테스트
(`tests/test_user_name_prompt_migration.py`)가 이 모듈을 `importlib` 로 불러 순수 함수와 `_patch_draft`·
`_delete_draft_rows` 를 직접 부른다.
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8e895c898730'
down_revision: str | Sequence[str] | None = '85df98c44368'
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
NEW_SET_IDS: dict[str, uuid.UUID] = {
    "story": uuid.UUID('7e6b6119-bc9c-4746-aecb-18cd5ee67c4f'),
    "character": uuid.UUID('3b80a001-83b1-4828-990c-9a94d3bcf61f'),
}
_SECTION_ID_NAMESPACE = uuid.UUID('60268c2f-bd60-43ff-8b9c-b9407a76797f')

_LANES: tuple[str, ...] = ("story", "character")
_SLOT = "user_name"

# 적용된 뒤에는 DB에 영구히 남는 값이라 문서명·번호를 넣지 않는다.
_NOTE = "사용자 이름 한 줄 섹션 추가"

# ---- 문안 ----------------------------------------------------------------------------------
# generation 채널의 다른 섹션은 `[머리글]` 로 시작하고, 판정·요약 채널은 머리글 없는 문장이 섞여 있다 — 채널의 모양을 따른다.
GENERATION_BODY = "[사용자 이름]\n대화 속 사용자의 이름: {user_name}"
JUDGMENT_BODY = "대화 속 사용자의 이름: {user_name}"

# 레인 → 채널 → (scope, 기준 slot, 기준 행 뒤에 둘지). 채널마다 같은 채널 형제 행의 scope 를 따른다.
_PLACEMENTS: dict[str, dict[str, tuple[str, str, bool]]] = {
    "story": {
        "generation": ("both", "user_persona", True),
        "stat_judgment": ("story", "turn_context", False),
        "ending_judgment": ("story", "memory_summary", False),
        "image_judgment": ("story", "turn_context", False),
        "memory_summary": ("both", "previous_summary", False),
    },
    "character": {
        "generation": ("both", "user_persona", True),
        "image_judgment": ("character", "turn_context", False),
        "memory_summary": ("both", "previous_summary", False),
    },
}

_CHECKED_CHANNELS: tuple[str, ...] = (
    "generation",
    "stat_judgment",
    "ending_judgment",
    "image_judgment",
    "memory_summary",
)

# 이 리비전 **이전**의 채널별 `(scope, slot, variant)` 기대 집합. `admin/prompts.py` 의 `_EXPECTED_ROWS_BY_LANE` 에서
# `user_name` 행을 뺀 것과 같다 — 앱 코드를 import 하지 않으므로 여기 다시 적는다. 레인에 없는 채널은 빈 집합이다.
_MEMORY_SUMMARY_BEFORE = frozenset({("both", "instruction", ""), ("both", "previous_summary", ""), ("both", "turn_context", "")})
_EXPECTED_BEFORE: dict[str, dict[str, frozenset[tuple[str, str, str]]]] = {
    "story": {
        "generation": frozenset(
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
                ("story", "situation_notes", ""),
                ("story", "shortcut_prompt", ""),
                ("both", "final_frame", ""),
            }
        ),
        "stat_judgment": frozenset(
            {("story", "stat_defs_intro", ""), ("story", "turn_context", ""), ("story", "judgment_instruction", "")}
        ),
        "ending_judgment": frozenset(
            {
                ("story", "memory_summary", ""),
                ("story", "history_header", ""),
                ("story", "turn_context", ""),
                ("story", "criteria", ""),
            }
        ),
        "image_judgment": frozenset(
            {("story", "image_list_intro", ""), ("story", "turn_context", ""), ("story", "judgment_instruction", "")}
        ),
        "memory_summary": _MEMORY_SUMMARY_BEFORE,
    },
    "character": {
        "generation": frozenset(
            {
                ("character", "character_prompt", ""),
                ("character", "example_dialogues", ""),
                ("both", "user_persona", ""),
                ("both", "memory_note", ""),
                ("both", "memory_summary", ""),
                ("both", "history", ""),
                ("both", "final_frame", ""),
            }
        ),
        "image_judgment": frozenset(
            {
                ("character", "image_list_intro", ""),
                ("character", "turn_context", ""),
                ("character", "judgment_instruction", ""),
            }
        ),
        "memory_summary": _MEMORY_SUMMARY_BEFORE,
    },
}

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

Row = tuple[str, str, str, str, str, bool, int]


def _describe(rows: Sequence[tuple[str, str, str, str, int]], channel: str) -> str:
    picked = sorted((order, scope, slot, variant) for ch, scope, slot, variant, order in rows if ch == channel)
    return ", ".join(f"{slot}{'/' + variant if variant else ''}({scope})={order}" for order, scope, slot, variant in picked)


def _assert_layout(rows: Sequence[tuple[str, str, str, str, int]], lane: str) -> dict[str, int]:
    """레인 세트 한 벌의 배치 가정을 검사하고 채널별 새 행의 자리 `X` 를 돌려준다.

    `rows` 는 `(channel, scope, slot, variant, order)` 목록이다. 검사하는 다섯 채널 중 하나라도 슬롯 집합이 이 리비전
    이전 기대와 다르면(이 행이 이미 있는 경우 포함) 레인과 실제 배치를 담은 `RuntimeError` 다(배포를 멈춘다)."""
    for channel in _CHECKED_CHANNELS:
        expected = _EXPECTED_BEFORE[lane].get(channel, frozenset())
        channel_rows = [(scope, slot, variant) for ch, scope, slot, variant, _ in rows if ch == channel]
        actual = set(channel_rows)
        if actual != expected or len(channel_rows) != len(expected):
            raise RuntimeError(
                f"[{lane}] {channel} 슬롯 집합이 이 리비전 이전 기대 집합과 다르다 — "
                f"누락 {sorted(expected - actual)}, 잉여 {sorted(actual - expected)}: {_describe(rows, channel)}"
            )

    insert_orders: dict[str, int] = {}
    for channel, (_scope, anchor_slot, after) in _PLACEMENTS[lane].items():
        anchor_order = next(order for ch, _, slot, _, order in rows if ch == channel and slot == anchor_slot)
        insert_orders[channel] = anchor_order + 1 if after else anchor_order
    return insert_orders


def _new_rows(lane: str, insert_orders: dict[str, int]) -> list[Row]:
    """레인에 더할 행 `(channel, scope, slot, variant, body, conditional, order)` 전부."""
    return [
        (channel, scope, _SLOT, "", GENERATION_BODY if channel == "generation" else JUDGMENT_BODY, True, insert_orders[channel])
        for channel, (scope, _anchor, _after) in _PLACEMENTS[lane].items()
    ]


def _shifted_order(channel: str, order: int, insert_orders: dict[str, int]) -> int:
    """기존 행의 새 order. 새 행이 들어가는 채널에서 그 자리 이상인 행만 +1."""
    insert_order = insert_orders.get(channel)
    return order + 1 if insert_order is not None and order >= insert_order else order


def _section_id(prefix: str, lane: str, channel: str, scope: str, slot: str, variant: str) -> uuid.UUID:
    return uuid.uuid5(_SECTION_ID_NAMESPACE, f"{prefix}{lane}:{channel}:{scope}:{slot}:{variant}")


def _build_published_rows(
    source_rows: Sequence[Row], lane: str, set_id: uuid.UUID, insert_orders: dict[str, int]
) -> list[dict[str, object]]:
    """원본 섹션 전부를 새 세트로 복사한 행 목록 + 이름 한 줄 행들. body·conditional·variant·scope 는 바이트 그대로
    두고 order 만 `_shifted_order` 로 민다."""
    copied = [
        (channel, scope, slot, variant, body, conditional, _shifted_order(channel, order, insert_orders))
        for channel, scope, slot, variant, body, conditional, order in source_rows
    ]
    return [
        {
            "id": _section_id("", lane, channel, scope, slot, variant),
            "prompt_set_id": set_id,
            "channel": channel,
            "scope": scope,
            "slot": slot,
            "variant": variant,
            "body": body,
            "conditional": conditional,
            "order": order,
        }
        for channel, scope, slot, variant, body, conditional, order in [*copied, *_new_rows(lane, insert_orders)]
    ]


def _patch_draft(conn: Connection, lane: str) -> bool:
    """레인에 초안이 없으면 `False`. 있으면 초안 **자신의** 배치로 가정을 검사한 뒤 새 행이 들어갈 채널의 `order >= X`
    행을 +1 하고(body 불변) 새 행을 넣고 `True`. 초안은 레인당 1개라(`ix_prompt_sets_draft`) 새 세트를 만들지 않고
    제자리에서 고친다.

    `op` 를 쓰지 않는다 — 테스트가 롤백되는 세션의 커넥션에 `run_sync` 로 부르기 위해서다."""
    draft_id = conn.execute(
        sa.text("SELECT id FROM prompt_sets WHERE status = 'draft' AND lane = :lane"), {"lane": lane}
    ).scalar_one_or_none()
    if draft_id is None:
        return False

    rows = conn.execute(_SECTIONS_SQL, {"id": draft_id}).fetchall()
    insert_orders = _assert_layout(
        [(channel, scope, slot, variant, order) for channel, scope, slot, variant, _body, _cond, order in rows], lane
    )
    for channel, insert_order in insert_orders.items():
        conn.execute(
            sa.text(
                'UPDATE prompt_sections SET "order" = "order" + 1'
                ' WHERE prompt_set_id = :id AND channel = :channel AND "order" >= :x'
            ),
            {"id": draft_id, "channel": channel, "x": insert_order},
        )
    conn.execute(
        sa.insert(prompt_sections_table),
        [
            {
                "id": _section_id("draft:", lane, channel, scope, slot, variant),
                "prompt_set_id": draft_id,
                "channel": channel,
                "scope": scope,
                "slot": slot,
                "variant": variant,
                "body": body,
                "conditional": conditional,
                "order": order,
            }
            for channel, scope, slot, variant, body, conditional, order in _new_rows(lane, insert_orders)
        ],
    )
    return True


def _delete_draft_rows(conn: Connection) -> None:
    """두 레인 초안의 이 행을 지우고 그 채널의 뒤 행을 −1 한다. 채널마다 행이 하나라 지우는 순서는 상관없다."""
    found = conn.execute(
        sa.text(
            'SELECT s.id, s.prompt_set_id, s.channel, s."order" FROM prompt_sections s'
            " JOIN prompt_sets p ON p.id = s.prompt_set_id"
            " WHERE p.status = 'draft' AND p.lane IN ('story', 'character') AND s.slot = :slot"
        ),
        {"slot": _SLOT},
    ).fetchall()
    for section_id, prompt_set_id, channel, order in found:
        conn.execute(sa.text("DELETE FROM prompt_sections WHERE id = :id"), {"id": section_id})
        conn.execute(
            sa.text(
                'UPDATE prompt_sections SET "order" = "order" - 1'
                ' WHERE prompt_set_id = :set_id AND channel = :channel AND "order" > :x'
            ),
            {"set_id": prompt_set_id, "channel": channel, "x": order},
        )


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    for lane in _LANES:  # story 먼저 — version 번호 순서
        source = bind.execute(_ACTIVE_SET_SQL, {"lane": lane}).one()
        rows = bind.execute(_SECTIONS_SQL, {"id": source.id}).fetchall()
        insert_orders = _assert_layout(
            [(channel, scope, slot, variant, order) for channel, scope, slot, variant, _b, _c, order in rows], lane
        )

        # `_next_published_version`(admin/prompts.py)과 같은 규칙 — 전 레인 대상.
        latest_version = bind.execute(
            sa.text("SELECT max(CAST(version AS INTEGER)) FROM prompt_sets WHERE status = 'published'")
        ).scalar_one()
        op.bulk_insert(
            prompt_sets_table,
            [
                {
                    "id": NEW_SET_IDS[lane],
                    "version": str((latest_version or 0) + 1),
                    "status": "published",
                    "lane": lane,
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
            prompt_sections_table,
            _build_published_rows([tuple(row) for row in rows], lane, NEW_SET_IDS[lane], insert_orders),
        )

        chosen = bind.execute(_ACTIVE_SET_SQL, {"lane": lane}).one().id
        if chosen != NEW_SET_IDS[lane]:
            raise RuntimeError(f"[{lane}] 새 세트가 활성으로 뽑히지 않는다: 활성={chosen}, 새 세트={NEW_SET_IDS[lane]}")

        _patch_draft(bind, lane)


def downgrade() -> None:
    """Downgrade schema."""
    ids = list(NEW_SET_IDS.values())
    op.execute(sa.delete(prompt_sections_table).where(prompt_sections_table.c.prompt_set_id.in_(ids)))
    op.execute(sa.delete(prompt_sets_table).where(prompt_sets_table.c.id.in_(ids)))
    _delete_draft_rows(op.get_bind())
