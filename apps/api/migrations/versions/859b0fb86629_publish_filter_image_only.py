"""publish filter image only

Revision ID: 859b0fb86629
Revises: c130656318eb
Create Date: 2026-10-03 12:00:00.000000

발행 심사가 작가가 쓴 글을 더는 보지 않고 첨부 이미지만 본다. 심사 프롬프트에는 이미지와, 코드가 만든 이미지 목록
라벨(`1. 대표 이미지` 뒤로 `2. 상황 이미지 1` 이나 `2. 미디어 북 민아·옥상` 꼴)만 싣는다. 그래서 publish_filter 레인의
슬롯이 서두(`intro_instruction`, character·story) · 이미지 목록(`image_list`, both, `{image_lines}`) · 판정
(`verdict_instruction`, both) 넷으로 줄어든다.

**publish_filter 레인 세트 전부(게시·초안)를 변환한다** — 옛 버전도 어드민에서 복원해 게시할 수 있게 남긴다.
세트마다 서두·판정이 아닌 작가 글 슬롯 행을 `publish_filter_text_section_backups` 로 원래 id·순서·본문 그대로
옮기고, `image_list` 행 하나를 더한다. 옛 세트의 서두·판정 본문과 순서는 한 글자도 바꾸지 않는다 — 그래서 옛 버전을
복원하면 "아래 텍스트와 함께" 같은 낡은 문구가 남는다(받아들인 제약). 운영 문안은 어드민에서 고쳐졌을 수 있어
시드 문안을 가정하지 않는다.

**레인으로만 거른다**(`prompt_sets.lane = 'publish_filter'`). legacy 세트에도 publish_filter channel 행이 있지만
어떤 코드도 렌더하지 않고 복원도 거부되므로 건드리지 않는다 — channel 로 거르면 legacy 까지 변환된다.

**`image_list` 의 order 는 그 세트 서두 order 중 큰 값 + 1** 이다. 판정 order 보다 작아야 서두 → 목록 → 판정
순으로 렌더되므로, 그 자리가 없으면 멈춘다. 빈 번호는 문제없다(렌더는 정렬만, 게시 검증은 중복만 본다).
`conditional=False` — 심사 시점엔 대표 이미지가 발행 검증으로 보장돼 목록이 비지 않는다.

**가정이 어긋나면 배포를 멈춘다**(`_assert_layout`): 세트의 행 `(channel, scope, slot, variant)` 집합이 미디어 북
슬롯 이전 16행 배치나 이후 17행 배치와 정확히 같지 않거나(행 수까지), 서두 뒤에 목록 자리가 없으면
`RuntimeError` 다. 본문은 보지 않는다. 체인이 한 트랜잭션이라(`migrations/env.py` `do_run_migrations`) 앞
리비전도 함께 롤백되고, 배포 스크립트가 `up -d` 전에 멈추므로 옛 코드·옛 DB 가 그대로 돈다.

**새 문안은 새 게시 세트로 활성화한다**(`NEW_SET_ID`). 버전은 어드민 게시와 같은 전 레인 자동 증가, 라벨은 지금
활성 세트에서 복사한다(발행 심사는 라벨을 읽지 않는다). `published_at` 은 SQL `now()` 가 아니라 파이썬
`max(now, 활성 + 1초)` 다 — 체인이 한 트랜잭션이라 SQL `now()` 는 체인 시작 시각이어서, 활성 세트가 같은
체인에서 만들어진 DB(테스트 DB)에서는 새 세트가 과거가 될 수 있다. 삽입 뒤 활성 SELECT 를 다시 돌려 확인한다.
publish_filter 레인은 활성 세트 캐시를 쓰지 않으므로(발행이 매번 DB 에서 읽는다) 지울 캐시가 없다.

⚠️ **운영 메모**:
- 마이그레이션이 끝나고 새 컨테이너가 뜨기까지 몇 초 동안 옛 코드가 새 활성 세트를 렌더하면 `{image_lines}` 값이
  없어 그 사이 발행이 500 이 된다. 다시 누르면 풀린다.
- 배포 전부터 있던 publish_filter 초안은 옛 서두·판정 + 이미지 목록 상태가 된다. 새 문안으로 편집하려면 새 세트를
  복원해 덮어쓴다. 배포 전부터 열어 둔 어드민 프롬프트 편집 탭은 새로고침한다.
- **이미지만 이전 태그로 되돌리면 안 된다** — 옛 코드는 작가 글 슬롯을 기대해 모든 발행이 500 이 된다. 반드시
  백업 후 **새 이미지로** `alembic downgrade c130656318eb` 를 먼저 하고(옛 이미지에는 이 리비전 파일이 없다) 곧바로
  이미지를 되돌린다. 둘 사이 몇 초 동안은 새 코드가 옛 세트를 렌더해 발행이 500 이 된다.

`downgrade()`: 이 리비전 뒤에 운영자가 publish_filter 세트를 새로 게시했거나 초안을 새로 만들었다면(백업 행이 없는,
이 리비전이 만든 것 아닌 세트) **아무것도 바꾸기 전에 그 id 를 알리며 멈춘다**. 게시 세트는 활성으로 남아 옛 코드의
발행을 깨뜨리고, 초안은 이미지 목록 4행 그대로 남아 옛 어드민의 게시·미리보기를 깨뜨리며 다시 업그레이드하는 배포도
배치 검사에서 막는다. 게시 이력·초안을 마이그레이션이 몰래 지우지 않는다. 운영자가 그 세트를 정리한 뒤(초안은 옛
버전을 복원해 덮거나 지운다) 다시 돌린다. 아니면 새 세트를 지우고(직전 활성
세트가 다시 활성이 된다), 백업 행이 있는 세트마다 `image_list` 행을 PK 가 아니라 세트·슬롯으로 찾아 지운 뒤(초안은
어드민 저장으로 섹션 PK 가 바뀌었을 수 있다) 백업 행을 되돌리고, 백업 테이블을 지운다. 업그레이드 뒤 편집된 초안은
서두·판정 order 가 바뀌어 복원 행과 겹칠 수 있다 — DB 제약이 없어 실패하지는 않고 게시 검증에서만 드러난다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 테스트(`tests/test_publish_filter_image_only_migration.py`)가
이 모듈을 `importlib` 로 불러 순수 함수와 `Connection` 을 받는 함수를 롤백되는 세션 커넥션에 직접 부른다.
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '859b0fb86629'
down_revision: str | Sequence[str] | None = 'c130656318eb'
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

BACKUP_TABLE = "publish_filter_text_section_backups"

# 리터럴 UUID — 작성 시점에 uuid.uuid4()를 한 번씩 실행해 뽑았다.
NEW_SET_ID = uuid.UUID('db13f4b4-8ac7-4351-87df-030d24ed5d5b')
_SECTION_ID_NAMESPACE = uuid.UUID('e0ce4686-9e4a-4904-8004-b081e2e460b9')

_LANE = "publish_filter"
_CHANNEL = "publish_filter"
_KEPT_SLOTS = ("intro_instruction", "verdict_instruction")
_IMAGE_LIST_SLOT = "image_list"

# 적용된 뒤에는 DB에 영구히 남는 값이라 문서명·번호를 넣지 않는다.
_NOTE = "발행 심사를 이미지 전용으로 전환 (작가 글 슬롯 제거, 이미지 목록 추가)"

# ---- 문안 ----------------------------------------------------------------------------------
# 목록 줄은 코드가 만든다(`content/publish.py` 의 빌더 — `n. 대표 이미지`, `n. 상황 이미지 k`,
# `n. 미디어 북 {인물}·{장면}`). 칸 라벨에는 작가가 지은 인물·장면 이름이 들어가므로 서두가 라벨은 식별용이라고
# 못박는다. 마지막 문장은 심사 범위를 긋는다 — 칸 그림이 스토리 내용과 맞지 않는다는 이유로 거부한 실측이 있었다.
# 판정 사유는 빌더가 작가에게 그대로 보여 주므로 어느 그림인지 목록의 라벨로 가리키게 한다.
_INTRO_SCREENING = (
    "각 이미지를 심사해 선정성/폭력성/혐오 표현/불법 콘텐츠 등 서비스에 부적절한 내용이 있는지 판단하라. "
    "심사 대상은 이미지뿐이다. 아래 목록의 라벨은 이미지를 가리키기 위한 식별용이며 심사 대상이 아니다. "
    "그림이 작품과 어울리는지는 심사 대상이 아니다."
)
CHARACTER_INTRO_BODY = (
    "다음은 사용자가 발행하려는 AI 캐릭터에 첨부된 이미지들이다(대표 이미지와 상황별 이미지). " + _INTRO_SCREENING
)
STORY_INTRO_BODY = (
    "다음은 사용자가 발행하려는 스토리 콘텐츠에 첨부된 이미지들이다(대표 이미지와 미디어 북 칸 그림). "
    + _INTRO_SCREENING
)
IMAGE_LIST_BODY = "[첨부 이미지 목록]\n첨부된 이미지는 아래 순서와 같다.\n{image_lines}"
VERDICT_BODY = (
    "부적절한 이미지가 없으면 passed=true, reason은 null로 응답하라. "
    "부적절한 이미지가 있으면 passed=false와 함께 어떤 이미지가 어떤 이유로 문제인지 reason에 한국어로 간결히 "
    "설명하라. 이미지는 위 목록의 라벨로 가리켜라."
)

# 이 리비전 **이전** publish_filter 세트 한 벌의 `(channel, scope, slot, variant)` 기대 집합 둘 — 미디어 북 칸 슬롯
# (`bd29dd69bc0f`) 이전 16행과 이후 17행. 옛 버전 게시본이 둘 다 남아 있을 수 있다. 앱 코드를 import 하지 않으므로
# 여기 다시 적는다. 게시 검증이 슬롯 집합을 고정하고 어드민 UI 로는 행을 더하거나 뺄 수 없다.
_LAYOUT_WITHOUT_MEDIA_BOOK: frozenset[tuple[str, str, str, str]] = frozenset(
    (_CHANNEL, scope, slot, "")
    for scope, slot in (
        ("character", "intro_instruction"),
        ("story", "intro_instruction"),
        ("both", "name"),
        ("both", "one_liner"),
        ("character", "intro"),
        ("story", "setting_text"),
        ("story", "development_example_legacy"),
        ("story", "custom_prompt"),
        ("story", "rules"),
        ("story", "user_goal"),
        ("story", "development_examples_pairs"),
        ("character", "example_dialogues"),
        ("character", "character_prompt"),
        ("both", "detail_description"),
        ("story", "starting_setups"),
        ("both", "verdict_instruction"),
    )
)
_LAYOUT_WITH_MEDIA_BOOK: frozenset[tuple[str, str, str, str]] = _LAYOUT_WITHOUT_MEDIA_BOOK | {
    (_CHANNEL, "story", "media_book", "")
}

# `load_active_prompt_set`(chat/prompt_builder.py)과 같은 규칙이다.
_ACTIVE_SET_SQL = sa.text(
    "SELECT id, user_label, story_assistant_label, story_example_label, character_assistant_label,"
    " published_at"
    " FROM prompt_sets WHERE status = 'published' AND lane = :lane"
    " ORDER BY published_at DESC LIMIT 1"
)


def _assert_layout(set_id: uuid.UUID, rows: Sequence[tuple[str, str, str, str, int]]) -> int:
    """세트 한 벌의 배치를 검사하고 `image_list` 행의 order 를 돌려준다.

    `rows` 는 그 세트의 `(channel, scope, slot, variant, order)` 전부다. 16행·17행 배치 중 하나와 정확히 같아야
    하고, 서두 order 중 큰 값 + 1 이 판정 order 보다 작아야 한다. 어긋나면 세트 id 와 실제 배치를 담은
    `RuntimeError` 다(배포를 멈춘다)."""
    ordered = sorted((order, channel, scope, slot, variant) for channel, scope, slot, variant, order in rows)
    layout = ", ".join(f"{channel}/{slot}({scope})={order}" for order, channel, scope, slot, _ in ordered)

    actual = {(channel, scope, slot, variant) for _, channel, scope, slot, variant in ordered}
    if len(ordered) != len(actual) or actual not in (_LAYOUT_WITHOUT_MEDIA_BOOK, _LAYOUT_WITH_MEDIA_BOOK):
        raise RuntimeError(
            f"[{_LANE}] 세트 {set_id} 의 슬롯 집합이 이 리비전 이전 배치(16행 또는 17행)와 다르다 — "
            f"누락 {sorted(_LAYOUT_WITHOUT_MEDIA_BOOK - actual)}, 잉여 {sorted(actual - _LAYOUT_WITH_MEDIA_BOOK)}: "
            f"{layout}"
        )

    image_list_order = max(order for order, _, _, slot, _ in ordered if slot == "intro_instruction") + 1
    verdict_order = next(order for order, _, _, slot, _ in ordered if slot == "verdict_instruction")
    if not image_list_order < verdict_order:
        raise RuntimeError(
            f"[{_LANE}] 세트 {set_id} 의 서두 뒤·판정(order={verdict_order}) 앞에 이미지 목록(order="
            f"{image_list_order})을 넣을 자리가 없다: {layout}"
        )
    return image_list_order


def _section_id(set_id: uuid.UUID, scope: str, slot: str) -> uuid.UUID:
    return uuid.uuid5(_SECTION_ID_NAMESPACE, f"{set_id}:{_CHANNEL}:{scope}:{slot}")


def _image_list_row(set_id: uuid.UUID, order: int) -> dict[str, object]:
    return {
        "id": _section_id(set_id, "both", _IMAGE_LIST_SLOT),
        "prompt_set_id": set_id,
        "channel": _CHANNEL,
        "scope": "both",
        "slot": _IMAGE_LIST_SLOT,
        "variant": "",
        "body": IMAGE_LIST_BODY,
        "conditional": False,
        "order": order,
    }


def _new_set_rows() -> list[dict[str, object]]:
    """새 게시 세트의 섹션 4행 — 서두(scope 별) 1, 이미지 목록 2, 판정 3."""
    return [
        {
            "id": _section_id(NEW_SET_ID, scope, slot),
            "prompt_set_id": NEW_SET_ID,
            "channel": _CHANNEL,
            "scope": scope,
            "slot": slot,
            "variant": "",
            "body": body,
            "conditional": False,
            "order": order,
        }
        for scope, slot, body, order in (
            ("character", "intro_instruction", CHARACTER_INTRO_BODY, 1),
            ("story", "intro_instruction", STORY_INTRO_BODY, 1),
            ("both", "verdict_instruction", VERDICT_BODY, 3),
        )
    ] + [_image_list_row(NEW_SET_ID, 2)]


def _convert_sets(conn: Connection) -> list[uuid.UUID]:
    """publish_filter 레인 세트 전부(게시·초안)를 검사한 뒤 변환하고, 변환한 세트 id 를 돌려준다.

    전부 먼저 검사하고 나서 고친다 — 하나라도 어긋나면 아무것도 바꾸지 않고 멈춘다(트랜잭션이 어차피 되감지만, 메시지가
    첫 어긋난 세트를 정확히 가리키게). `op` 를 쓰지 않는다 — 테스트가 롤백되는 세션 커넥션에 `run_sync` 로 부른다."""
    set_ids = list(
        conn.execute(
            sa.text("SELECT id FROM prompt_sets WHERE lane = :lane AND id <> :new_id ORDER BY id"),
            {"lane": _LANE, "new_id": NEW_SET_ID},
        ).scalars()
    )
    image_list_orders: dict[uuid.UUID, int] = {}
    for set_id in set_ids:
        rows = conn.execute(
            sa.text('SELECT channel, scope, slot, variant, "order" FROM prompt_sections WHERE prompt_set_id = :id'),
            {"id": set_id},
        ).fetchall()
        image_list_orders[set_id] = _assert_layout(set_id, [tuple(row) for row in rows])

    for set_id, image_list_order in image_list_orders.items():
        moved = {"id": set_id, "kept": list(_KEPT_SLOTS)}
        conn.execute(
            sa.text(
                f'INSERT INTO {BACKUP_TABLE} (id, prompt_set_id, channel, scope, slot, variant, body, conditional, "order")'
                ' SELECT id, prompt_set_id, channel, scope, slot, variant, body, conditional, "order"'
                " FROM prompt_sections WHERE prompt_set_id = :id AND slot <> ALL(:kept)"
            ),
            moved,
        )
        conn.execute(sa.text("DELETE FROM prompt_sections WHERE prompt_set_id = :id AND slot <> ALL(:kept)"), moved)
        conn.execute(sa.insert(prompt_sections_table).values(_image_list_row(set_id, image_list_order)))
    return set_ids


def _publish_new_set(conn: Connection) -> None:
    """새 문안을 담은 게시 세트를 만들고 그것이 활성으로 뽑히는지 확인한다."""
    source = conn.execute(_ACTIVE_SET_SQL, {"lane": _LANE}).one()
    # `_next_published_version`(admin/prompts.py)과 같은 규칙 — 전 레인 대상.
    latest_version = conn.execute(
        sa.text("SELECT max(CAST(version AS INTEGER)) FROM prompt_sets WHERE status = 'published'")
    ).scalar_one()
    conn.execute(
        sa.insert(prompt_sets_table).values(
            id=NEW_SET_ID,
            version=str((latest_version or 0) + 1),
            status="published",
            lane=_LANE,
            user_label=source.user_label,
            story_assistant_label=source.story_assistant_label,
            story_example_label=source.story_example_label,
            character_assistant_label=source.character_assistant_label,
            note=_NOTE,
            # SQL now()가 아니다 — 위 docstring.
            published_at=max(datetime.now(UTC), source.published_at + timedelta(seconds=1)),
        )
    )
    conn.execute(sa.insert(prompt_sections_table), _new_set_rows())

    chosen = conn.execute(_ACTIVE_SET_SQL, {"lane": _LANE}).one().id
    if chosen != NEW_SET_ID:
        raise RuntimeError(f"[{_LANE}] 새 세트가 활성으로 뽑히지 않는다: 활성={chosen}, 새 세트={NEW_SET_ID}")


def _assert_no_set_created_after(conn: Connection) -> None:
    """이 리비전 뒤에 생긴 publish_filter 세트(게시·초안)가 있으면 아무것도 바꾸기 전에 멈춘다. 그런 세트는 백업 행이
    없다 — 이 리비전 이전 세트는 전부 작가 글 행을 백업으로 옮겼고, 어드민 게시는 늘 새 id 로 세트를 만들며, 초안이
    없던 레인을 저장하면 새 id 의 초안이 생긴다. 게시 세트는 되돌린 뒤 활성으로 남아 옛 코드의 발행을 깨뜨리고, 초안은
    이미지 목록만 든 채 남아 옛 코드 어드민의 게시·미리보기를 깨뜨리고 다시 업그레이드할 때 배치 검사에 걸린다."""
    later = conn.execute(
        sa.text(
            "SELECT id, status FROM prompt_sets p WHERE p.lane = :lane AND p.id <> :new_id"
            f" AND NOT EXISTS (SELECT 1 FROM {BACKUP_TABLE} b WHERE b.prompt_set_id = p.id)"
            " ORDER BY p.created_at, p.id"
        ),
        {"lane": _LANE, "new_id": NEW_SET_ID},
    ).fetchall()
    if later:
        raise RuntimeError(
            f"[{_LANE}] 이 리비전 뒤에 생긴 발행 심사 세트가 있다: "
            f"{', '.join(f'{set_id}({status})' for set_id, status in later)} — 게시 세트는 되돌린 뒤 활성으로 남아 옛 코드의"
            " 발행이 실패하고, 초안은 옛 어드민에서 게시·미리보기가 깨진다. 그 세트를 정리한 뒤(초안은 옛 버전을 복원해"
            " 덮거나 지운다) 다시 돌린다."
        )


def _restore_sets(conn: Connection) -> None:
    """새 세트를 지우고, 백업 행이 있는 세트마다 `image_list` 행을 지운 뒤 백업 행을 원래대로 되돌린다."""
    _assert_no_set_created_after(conn)
    conn.execute(sa.delete(prompt_sections_table).where(prompt_sections_table.c.prompt_set_id == NEW_SET_ID))
    conn.execute(sa.delete(prompt_sets_table).where(prompt_sets_table.c.id == NEW_SET_ID))

    backed_up = {"channel": _CHANNEL, "slot": _IMAGE_LIST_SLOT}
    conn.execute(
        sa.text(
            "DELETE FROM prompt_sections WHERE channel = :channel AND slot = :slot"
            f" AND prompt_set_id IN (SELECT DISTINCT prompt_set_id FROM {BACKUP_TABLE})"
        ),
        backed_up,
    )
    conn.execute(
        sa.text(
            'INSERT INTO prompt_sections (id, prompt_set_id, channel, scope, slot, variant, body, conditional, "order")'
            ' SELECT id, prompt_set_id, channel, scope, slot, variant, body, conditional, "order"'
            f" FROM {BACKUP_TABLE}"
        )
    )
    conn.execute(sa.text(f"DELETE FROM {BACKUP_TABLE}"))


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        BACKUP_TABLE,
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('prompt_set_id', sa.Uuid(), nullable=False),
        sa.Column('channel', sa.Text(), nullable=False),
        sa.Column('scope', sa.Text(), nullable=False),
        sa.Column('slot', sa.Text(), nullable=False),
        sa.Column('variant', sa.Text(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('conditional', sa.Boolean(), nullable=False),
        sa.Column('order', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['prompt_set_id'], ['prompt_sets.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    bind = op.get_bind()
    _convert_sets(bind)
    _publish_new_set(bind)


def downgrade() -> None:
    """Downgrade schema."""
    _restore_sets(op.get_bind())
    op.drop_table(BACKUP_TABLE)
