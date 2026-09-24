"""prompt sections user persona slot

Revision ID: b72c33c70240
Revises: 59d627a75fbf
Create Date: 2026-09-24 17:10:00.000000

persona-goal-prompt.md §3-2 M2 (UP-13·UP-18·UP-19). 대화 생성 채널에 conditional 섹션
`('generation', 'both', 'user_persona', '')`을 넣는다. story·character 두 레인에 같은 규칙을
적용한다.

**기존 published 세트는 건드리지 않는다(UP-13).** 레인의 활성 세트를 복사한 **새 published
세트**를 만들고, 거기에 행 하나를 더한다. 어드민 UI에는 행을 추가하는 기능이 없어서 데이터
마이그레이션이 넣는다.

**위치는 절대 order가 아니라 `history` 바로 앞이다(UP-18 (a) + 보충).** 운영자는 어드민의
위·아래 버튼으로 order를 맞바꿀 수 있다(F10). 그래서 `history`의 현재 order를 `H`로 읽고,
generation 채널에서 `order >= H`인 행을 전부 +1 한 뒤 새 행을 `H`에 둔다. 나머지 행의 상대
순서가 그대로라서, 프로필 값이 비면(섹션 드롭, F1) 렌더 결과가 바이트까지 같다(UP-6).

**가정이 어긋나면 배포를 멈춘다**(`_assert_generation_layout`). 조용히 이상한 세트를 게시하지
않기 위해서다. 체인이 한 트랜잭션이라(`migrations/env.py` `do_run_migrations`) M1도 함께
롤백된다. 멈추는 경우: generation 슬롯 집합이 M2 이전 기대 집합과 다름, `user_persona`가 이미
있음, story에서 `prologue`가 `history` 뒤에 있음(UP-18 (a)의 "prologue 뒤, history 앞"을
동시에 만족할 수 없다 — 사용자에게 물을 일이다).

**`published_at`은 SQL `now()`가 아니라 파이썬 `max(now, 원본 + 1초)`다.** 체인이 한
트랜잭션이라 SQL `now()`는 체인 **시작** 시각이다. 테스트 DB처럼 체인 도중에 원본 세트가
만들어진 경우(`a69cbd40dec8`) 새 세트가 원본보다 과거가 되어 활성이 되지 못할 수 있다
(persona-goal-prompt.md R-21). 삽입 뒤에는 활성 SELECT를 다시 돌려 새 세트가 뽑히는지
확인한다.

**초안(UP-19 (a))**: 레인에 초안이 있으면 초안에도 같은 행을 **제자리에서** 넣고 order를 민다
(`_patch_draft`). body는 건드리지 않는다. 없으면 no-op이다(2026-09-24 프로덕션 실측은 0건,
`tasks/persona-research/s0-prod.md`).

**PK**: 새 세트 2개는 리터럴 UUID(`NEW_SET_IDS`). 섹션은 세트마다 개수가 달라 리터럴을 나열할
수 없으므로 `uuid5(_SECTION_ID_NAMESPACE, "{lane}:{channel}:{scope}:{slot}:{variant}")`로
결정적으로 만든다(`uuid4()` 호출 금지 규약). 초안에 넣는 행은 같은 키와 겹치지 않게 `draft:`
접두사를 붙인다.

⚠️ **운영 메모** (persona-goal-prompt.md R-6·R-7·R-8):
- 이 슬롯의 body에서 `{user_persona}`를 지우면 드롭 조건(`bool(fields)`)이 거짓이 되어
  **모든 유저에게 머리글만 나간다**. 게시 검증 R-4는 "허용 밖 이름"만 막고 "필수 이름의 존재"는
  보지 않는다.
- 배포 전부터 열어 둔 어드민 프롬프트 편집 탭에서 저장하면 초안이 섹션 전체 교체로
  `user_persona` 행을 잃고 게시가 R-1 "누락"으로 막힌다. **배포 뒤에는 편집 탭을 새로고침한다.**
  이미 그렇게 됐으면 이 리비전의 세트(또는 그 뒤 게시본)를 복원해 초안을 다시 만든다.
- **슬롯 추가 이전 버전은 복원해도 게시할 수 없다**(R-1 "누락", UP-20 (a)에서 제약으로
  받아들임). 문안 롤백은 슬롯 추가 이후 버전끼리만 한다. 이 리비전의 세트는 직전 세트 body를
  그대로 복사하고 행 하나만 더한 것이라 직전 세트의 대체물이 된다.
- 마이그레이션은 활성 세트 캐시를 지우지 않는다 — 배포 직후 최대 300초
  (`prompt_set_cache_ttl_seconds`) 동안 옛 세트가 나간다. 옛 세트에는 슬롯이 없어 프로필이
  반영되지 않을 뿐 해가 없다.

**롤백**(persona-goal-prompt.md §3-2 롤백 절차, R-9): 1순위는 태그 롤백(이미지만 되돌리고
스키마·세트는 그대로)이다. 옛 코드는 값을 넘기지 않으므로 새 섹션은 드롭되어 안전하다. 다만
옛 R-1이 새 세트를 "잉여"로 거부하므로 그 상태에서 다음 게시가 필요하면 슬롯 추가 이전 버전을
복원해서 게시한다. revert 커밋을 main에 push하면 자동 배포의 `alembic upgrade head`가 이
리비전을 찾지 못해 멈춘다 — 먼저 태그 롤백 → 백업 → **이 파일이 든 새 이미지로**
`alembic downgrade cf74d6d53561` → 그다음 revert push 순서로 한다(프로필 데이터가 사라진다).

`downgrade()`: 리터럴 세트의 섹션 → 세트 순으로 지운다. 초안에 넣은 `user_persona` 행은 PK가
아니라 slot으로 찾는다(초안 upsert가 섹션을 통째로 교체하므로 PK가 바뀌어 있을 수 있다). 그
order `X`를 읽고 지운 뒤 `order > X`인 generation 행을 −1 한다. 그 사이 운영자가 게시한 새
버전(프로필 행 포함)은 남는다.

이 파일은 `api.*`를 import하지 않는다(저장소 관례, `cf74d6d53561` docstring). 기대 슬롯
집합과 body 문안은 여기 리터럴로 둔다. 테스트는 `tests/test_persona_prompt_slot_migration.py`가
이 모듈을 `importlib`로 불러 순수 함수와 `_patch_draft`를 직접 부른다.
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b72c33c70240'
down_revision: str | Sequence[str] | None = '59d627a75fbf'
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
    "story": uuid.UUID('f6f9c6ee-a09a-4808-9c6c-c8d8b55b1c99'),
    "character": uuid.UUID('3ac66700-3fed-4cb3-bd4b-b8aeeca5e4a7'),
}
_SECTION_ID_NAMESPACE = uuid.UUID('a1c645f1-172e-4bf9-8655-a87a29b204eb')

_LANES: tuple[str, ...] = ("story", "character")

_NOTE = "대화 프로필 슬롯 추가 (persona-goal-prompt.md UP-13)"

# persona-goal-prompt.md §3-4-3 확정 문안(UP-17). `{user_persona}`가 빠지면 이 섹션은 절대
# 드롭되지 않는다(위 운영 메모).
PERSONA_BODY = (
    "[사용자 정보]\n"
    "아래는 사용자가 스스로 정한 자기 설정이다. 작품 설정이 사용자에게 정해 둔 역할이나 세계관이 "
    "있으면 그것이 우선하고, 이 정보는 그 위에 이름·성별·특징을 덧붙이는 참고로만 쓴다.\n"
    "{user_persona}"
)
_PERSONA_SLOT = "user_persona"

# M2 **이전**의 generation `(scope, slot, variant)` 기대 집합(persona-goal-prompt.md F9).
# `admin/prompts.py`의 `_EXPECTED_ROWS_BY_LANE`에서 `user_persona`를 뺀 것과 같다 — 앱 코드를
# import하지 않으므로 여기 다시 적는다. R-1이 이 집합을 고정하고 어드민 UI로는 행을 더하거나
# 뺄 수 없어서(F10) 재배치와 무관하게 성립한다.
_EXPECTED_GENERATION_BEFORE: dict[str, frozenset[tuple[str, str, str]]] = {
    "story": frozenset(
        {
            ("story", "base_content", ""),
            ("story", "base_content", "custom"),
            ("story", "rules", ""),
            ("story", "user_goal", ""),
            ("story", "development_examples", ""),
            ("story", "prologue", ""),
            ("both", "history", ""),
            ("story", "keyword_notes", ""),
            ("story", "shortcut_prompt", ""),
            ("both", "final_frame", ""),
        }
    ),
    "character": frozenset(
        {
            ("character", "character_prompt", ""),
            ("character", "example_dialogues", ""),
            ("both", "history", ""),
            ("both", "final_frame", ""),
        }
    ),
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


def _assert_generation_layout(rows: Sequence[tuple[str, str, str, str, int]], lane: str) -> int:
    """M2가 기대는 배치 가정을 검사하고 삽입 order `H`(= `history`의 현재 order)를 돌려준다.

    `rows`는 `(channel, scope, slot, variant, order)` 목록이다. generation 밖의 행은 보지
    않는다. 어긋나면 레인과 실제 배치를 담은 `RuntimeError`다(배포를 멈춘다)."""
    generation = sorted((order, scope, slot, variant) for channel, scope, slot, variant, order in rows if channel == "generation")
    layout = ", ".join(f"{slot}{'/' + variant if variant else ''}({scope})={order}" for order, scope, slot, variant in generation)

    if any(slot == _PERSONA_SLOT for _, _, slot, _ in generation):
        raise RuntimeError(f"[{lane}] generation에 {_PERSONA_SLOT} 행이 이미 있다: {layout}")

    actual = {(scope, slot, variant) for _, scope, slot, variant in generation}
    expected = _EXPECTED_GENERATION_BEFORE[lane]
    if actual != expected or len(generation) != len(expected):
        raise RuntimeError(
            f"[{lane}] generation 슬롯 집합이 M2 이전 기대 집합과 다르다 — "
            f"누락 {sorted(expected - actual)}, 잉여 {sorted(actual - expected)}: {layout}"
        )

    orders = {slot: order for order, _, slot, variant in generation if variant == ""}
    insert_order = orders["history"]
    if lane == "story" and not orders["prologue"] < insert_order:
        raise RuntimeError(
            f"[{lane}] prologue(order={orders['prologue']})가 history(order={insert_order}) 앞에 있지 않다 — "
            f"UP-18 (a)의 'prologue 뒤, history 앞'을 동시에 만족할 수 없다: {layout}"
        )
    return insert_order


def _build_published_rows(
    source_rows: Sequence[tuple[str, str, str, str, str, bool, int]],
    lane: str,
    set_id: uuid.UUID,
    insert_order: int,
) -> list[dict[str, object]]:
    """원본 섹션 전부를 새 세트로 복사한 행 목록 + `user_persona` 행 하나.

    `source_rows`는 `(channel, scope, slot, variant, body, conditional, order)` 목록이다.
    body·conditional·variant·scope는 바이트 그대로 두고, generation 채널에서
    `order >= insert_order`인 행만 +1 한다(scope·variant와 무관, `history` 자신 포함). 그래서
    `insert_order`에는 새 행 하나만 남는다."""

    def section_id(channel: str, scope: str, slot: str, variant: str) -> uuid.UUID:
        return uuid.uuid5(_SECTION_ID_NAMESPACE, f"{lane}:{channel}:{scope}:{slot}:{variant}")

    built: list[dict[str, object]] = [
        {
            "id": section_id(channel, scope, slot, variant),
            "prompt_set_id": set_id,
            "channel": channel,
            "scope": scope,
            "slot": slot,
            "variant": variant,
            "body": body,
            "conditional": conditional,
            "order": order + 1 if channel == "generation" and order >= insert_order else order,
        }
        for channel, scope, slot, variant, body, conditional, order in source_rows
    ]
    built.append(
        {
            "id": section_id("generation", "both", _PERSONA_SLOT, ""),
            "prompt_set_id": set_id,
            "channel": "generation",
            "scope": "both",
            "slot": _PERSONA_SLOT,
            "variant": "",
            "body": PERSONA_BODY,
            "conditional": True,
            "order": insert_order,
        }
    )
    return built


def _patch_draft(conn: Connection, lane: str) -> bool:
    """UP-19 (a). 레인에 초안이 없으면 `False`. 있으면 초안 **자신의** 배치로 가정을 검사한 뒤
    (초안의 `H`는 활성 세트와 다를 수 있다) 기존 행은 order만 민다(`order >= H` +1, body 불변).
    그다음 `user_persona` 행을 order `H`로 더하고 `True`를 돌려준다. 초안은 레인당 1개라
    (`ix_prompt_sets_draft`) 새 세트를 만들지 않고 제자리에서 고친다.

    `op`를 쓰지 않는다 — 테스트가 롤백되는 세션의 커넥션에 `run_sync`로 부르기 위해서다."""
    draft_id = conn.execute(
        sa.text("SELECT id FROM prompt_sets WHERE status = 'draft' AND lane = :lane"), {"lane": lane}
    ).scalar_one_or_none()
    if draft_id is None:
        return False

    rows = conn.execute(_SECTIONS_SQL, {"id": draft_id}).fetchall()
    insert_order = _assert_generation_layout(
        [(channel, scope, slot, variant, order) for channel, scope, slot, variant, _body, _cond, order in rows], lane
    )
    conn.execute(
        sa.text(
            'UPDATE prompt_sections SET "order" = "order" + 1'
            " WHERE prompt_set_id = :id AND channel = 'generation' AND \"order\" >= :h"
        ),
        {"id": draft_id, "h": insert_order},
    )
    conn.execute(
        sa.insert(prompt_sections_table).values(
            id=uuid.uuid5(_SECTION_ID_NAMESPACE, f"draft:{lane}:generation:both:{_PERSONA_SLOT}:"),
            prompt_set_id=draft_id,
            channel="generation",
            scope="both",
            slot=_PERSONA_SLOT,
            variant="",
            body=PERSONA_BODY,
            conditional=True,
            order=insert_order,
        )
    )
    return True


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    for lane in _LANES:  # story 먼저 — version 번호 순서(§3-2 M2 3번)
        source = bind.execute(_ACTIVE_SET_SQL, {"lane": lane}).one()
        rows = bind.execute(_SECTIONS_SQL, {"id": source.id}).fetchall()
        insert_order = _assert_generation_layout(
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
                    # SQL now()가 아니다 — 위 docstring(R-21).
                    "published_at": max(datetime.now(UTC), source.published_at + timedelta(seconds=1)),
                }
            ],
        )
        op.bulk_insert(
            prompt_sections_table,
            _build_published_rows([tuple(row) for row in rows], lane, NEW_SET_IDS[lane], insert_order),
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

    bind = op.get_bind()
    draft_rows = bind.execute(
        sa.text(
            'SELECT s.id, s.prompt_set_id, s."order" FROM prompt_sections s'
            " JOIN prompt_sets p ON p.id = s.prompt_set_id"
            " WHERE p.status = 'draft' AND s.channel = 'generation' AND s.slot = :slot"
        ),
        {"slot": _PERSONA_SLOT},
    ).fetchall()
    for section_id, prompt_set_id, order in draft_rows:
        bind.execute(sa.text("DELETE FROM prompt_sections WHERE id = :id"), {"id": section_id})
        bind.execute(
            sa.text(
                'UPDATE prompt_sections SET "order" = "order" - 1'
                " WHERE prompt_set_id = :set_id AND channel = 'generation' AND \"order\" > :x"
            ),
            {"set_id": prompt_set_id, "x": order},
        )
