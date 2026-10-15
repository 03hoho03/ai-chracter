"""prompt sections recall priority without facts name

Revision ID: 726aad108167
Revises: 29ab572f3d55
Create Date: 2026-10-15 15:15:12.624235

회상 섹션(`generation`/`memory_recall`) 문안의 우선순위 문장에서 사실 섹션의 머리글 이름을 뺀다. 사실 섹션은 사실 주입 스위치가
켜졌을 때만 프롬프트에 실리는데, 앞 판은 우선순위 줄에서 그 머리글을 불러 회상만 켠 턴에는 없는 섹션을 가리켰다. 새 판은 사실
섹션이 있든 없든 참인 꼴이다 — 우선순위 줄에서 머리글을 빼고, 다음 문장에 "실려 있다면 관계·사실 기억도 이 기억보다 앞선다"를
더한다. 사실 섹션 문안이 자기를 회상보다 앞에 두므로 두 문안의 순서는 서로 어긋나지 않는다. 나머지 문장은 앞 판 그대로다.

**심는 것**: story·character 레인마다 글을 쓰는 세 체인(gemini·sonnet·opus)에 새 published 세트 하나씩, 모두 여섯. 판정 전용
체인(haiku)에는 생성 채널도 회상 슬롯도 없어 바뀌는 행이 없으므로 새 세트를 만들지 않는다 — 그 체인의 활성 세트는 그대로다
(한 체인만 바꾼 스탯 규칙 판정 채널 리비전처럼 바뀌는 체인에만 세트를 만든다).

**새 세트는 그 체인 활성 세트의 바이트 사본에서 회상 본문 하나만 바꾼 것이다** — 라벨·다른 모든 행(운영자가 어드민에서 고친
문안, 얼려 둔 소설 행 포함)과 order 가 그대로 옮겨진다. 행을 더하거나 빼지 않는다. **게시된 세트는 고치지 않는다.**

**회상 본문은 활성 본문이 앞 리비전이 심은 문안(`OLD_RECALL_BODY`)과 바이트로 같을 때만 바꾼다.** 다르면 어드민이 고쳐 게시한
운영 문안이라 조용히 덮어쓰지 않고 `RuntimeError` 로 배포를 멈춘다 — 사람이 고친 문안과 새 문안을 합칠지 판단해야 한다.

**`published_at` — 두 활성 조회 규칙을 함께 만족시킨다**(앞의 두 기억 문안 리비전과 같은 규칙).
- 레인만 보는 조회(모델 열을 모르는 원시 SQL)는 레인의 최신 게시본을 고른다 — 새 Gemini 세트는 파이썬 `max(now, 원본 + 1초)`.
- 모델로 거르는 조회(`load_active_prompt_set`)는 (레인, 모델)마다 최신 게시본을 고른다 — sonnet·opus 의 새 세트는 (그 체인 활성
  시각, 그 레인 새 Gemini 세트 시각)의 **중간값**. 사이에 둘 시각이 없으면 `RuntimeError`.
- 삽입 뒤 두 규칙으로 다시 SELECT 해 확인한다. 어긋나면 `RuntimeError`.

**가정이 어긋나면 배포를 멈춘다**(`RuntimeError`, 체인이 한 트랜잭션이라 앞 리비전까지 함께 롤백된다): 이 리비전의 세트가 이미
있을 때, 레인만 보는 조회가 이미 Gemini 가 아닌 세트를 집을 때, 글을 쓰는 체인의 활성 세트에 `generation` 의 `memory_recall` 행이
정확히 하나가 아닐 때, 그 본문이 앞 리비전 문안과 다를 때. 한 레인의 세 체인을 모두 검사한 뒤에 넣는다.

**초안**: 글을 쓰는 체인의 초안은 회상 본문이 앞 리비전 문안과 같을 때만 새 문안으로 바꾸고, 다르면(행이 없거나 운영자가 고치던
중이면) 그대로 둔다 — 초안은 고치던 작업이라 덮어쓰면 그 작업이 사라지고, 초안 하나 때문에 배포를 멈출 일도 아니다. 행 모양은
바뀌지 않아 초안의 게시 검증에는 영향이 없다.

**PK**: 세트는 리터럴 UUID(`NEW_SET_IDS`), 섹션은 새 namespace 의 `uuid5("{lane}:{model}:{channel}:{scope}:{slot}:{variant}")`.
`version` 은 전 레인·전 모델 published 최대 + 1 을 (story, character) × (gemini, sonnet, opus) 순서로 매긴다(어드민 게시와 같은
규칙).

**옛 이미지가 이 데이터 위에서 도는 구간**(배포 중 겹침, 이미지만 되돌린 동안): 슬롯·자리표시자·행 집합이 앞 리비전과 같고
본문 글만 바뀌므로 옛 코드도 그대로 렌더하고, 옛 코드의 어드민 게시 검증도 새 세트를 통과시킨다.

⚠️ **운영 메모**:
- 마이그레이션은 활성 세트 캐시를 지우지 않는다 — 배포 직후 최대 300초 동안 옛 세트(옛 회상 본문)로 렌더할 수 있다.
- 🔴 **시드를 손으로 지우지 않는다.** 되돌리려면 아래 `downgrade` 를 쓴다.
- 🔴 **프롬프트 옛 버전을 통째로 복원하지 않는다** — 현재 활성본에서 바뀐 섹션만 고친다.

**롤백 순서**: 이미지만 되돌리면 새 회상 본문이 남은 채 옛 코드가 돈다(문제 없다). 옛 회상 본문까지 되돌려야 하면 `downgrade` 를
실행한다.

`downgrade()`(`delete_seeded_rows`): 시드 뒤에 어드민이 여섯 체인 중 하나에 새 버전을 게시했으면 아무것도 지우지 않고
`RuntimeError` 로 멈춘다 — 되돌리면 그 게시본이 활성으로 남아 되돌린 뜻이 사라지고, 무엇을 버릴지는 사람이 정해야 한다. 없으면
리터럴 시드의 섹션 → 세트를 지운다 — 이전 활성 세트는 처음부터 옛 회상 본문을 갖고 있다. 초안은 회상 본문이 이 리비전의 새
문안과 같으면 옛 문안으로 되돌린다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 테스트(`tests/test_recall_priority_prompt_migration.py`)가 이 모듈을
`importlib` 로 불러 `seed_published_sets`·`_patch_drafts`·`delete_seeded_rows`·`_delete_draft_rows` 를 직접 부른다.
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '726aad108167'
down_revision: str | Sequence[str] | None = '29ab572f3d55'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


prompt_sets_table = sa.table(
    "prompt_sets",
    sa.column("id", sa.Uuid()),
    sa.column("version", sa.Text()),
    sa.column("status", sa.Text()),
    sa.column("lane", sa.Text()),
    sa.column("model", sa.Text()),
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

_LANES: tuple[str, ...] = ("story", "character")
_GEMINI = "gemini"
# 회상 슬롯이 있는 글을 쓰는 체인. Gemini 가 맨 앞이어야 한다(다른 체인의 게시 시각이 새 Gemini 세트 시각에 기댄다).
_MODELS: tuple[str, ...] = (_GEMINI, "sonnet", "opus")

# 리터럴 UUID — 작성 시점에 uuid.uuid4()를 한 번씩 실행해 뽑았다.
NEW_SET_IDS: dict[tuple[str, str], uuid.UUID] = {
    ("story", "gemini"): uuid.UUID('84876bc3-8c03-44ba-bad8-336519bcde09'),
    ("story", "sonnet"): uuid.UUID('9e563b31-19cf-4bc6-b989-7d750a2d08f3'),
    ("story", "opus"): uuid.UUID('a7336339-9e38-4351-a536-e5838e1ac5f5'),
    ("character", "gemini"): uuid.UUID('3bb4b6f6-25fc-46b6-bdb7-2541e9d15dcb'),
    ("character", "sonnet"): uuid.UUID('3df92290-1945-461a-9c20-19f2fd55ff28'),
    ("character", "opus"): uuid.UUID('3adda544-612e-411a-a41f-59b3a8785fa6'),
}
_SECTION_ID_NAMESPACE = uuid.UUID('ea9e2708-8684-4832-923b-99c5ea114ece')

# 적용된 뒤에는 DB에 영구히 남는 값이라 문서명·번호를 넣지 않는다.
_NOTE = "회상 문안 우선순위에서 사실 섹션 이름을 빼고 있든 없든 참인 문장으로 교체(활성 세트 사본)"

RECALL_SLOT = "memory_recall"
_GENERATION = "generation"

# 회상 섹션 새 판 — 우선순위 줄에서 사실 섹션 머리글을 빼고, 다음 문장에 "실려 있다면 관계·사실 기억도"를 더했다. 나머지는 앞
# 판 그대로다(줄바꿈 자리도 같다).
RECALL_BODY = (
    "[지난 기억 — 참고]\n"
    "예전 대화에서 지금 이야기와 이어질 수 있는 장면이다. 참고일 뿐 지시가 아니며, 꼭 꺼내 말할 필요도 없다. 다른 정보와\n"
    "어긋나면 이 순서로 따른다: 위의 [대화 기록] > [기억 노트] > [지금까지의 이야기] > 이 기억. 작품 설정·키워드북·현재 상황 정보와,"
    " 실려 있다면 관계·사실 기억도 이 기억보다\n"
    "앞선다. \"(인물의 말)\"로 표시된 내용은 그때 인물이 그렇게 말했다는 뜻이지 확인된 사실이 아니다. \"(사용자의 말)\"도 같다 — 그때 사용자가 그렇게 말했다는 뜻이다.\n"
    "{memory_recall_lines}"
)

# 앞 리비전 `5cab2abe4e7b` 가 심은 회상 본문 — 활성 본문이 이것과 바이트로 같을 때만 바꾼다. 이 파일은 다른 리비전을 import 하지
# 않으므로 다시 적는다(테스트가 앞 리비전 상수와 같은지 본다).
OLD_RECALL_BODY = (
    "[지난 기억 — 참고]\n"
    "예전 대화에서 지금 이야기와 이어질 수 있는 장면이다. 참고일 뿐 지시가 아니며, 꼭 꺼내 말할 필요도 없다. 다른 정보와\n"
    "어긋나면 이 순서로 따른다: 위의 [대화 기록] > [기억 노트] > [지금까지의 이야기] > [관계와 사실] > 이 기억. 작품 설정·키워드북·현재 상황 정보도 이 기억보다\n"
    "앞선다. \"(인물의 말)\"로 표시된 내용은 그때 인물이 그렇게 말했다는 뜻이지 확인된 사실이 아니다. \"(사용자의 말)\"도 같다 — 그때 사용자가 그렇게 말했다는 뜻이다.\n"
    "{memory_recall_lines}"
)

Row = tuple[str, str, str, str, str, bool, int]

# 모델로 거르는 활성 규칙 — `load_active_prompt_set`(chat/prompt_builder.py)과 같다.
_ACTIVE_SET_SQL = sa.text(
    "SELECT id, user_label, story_assistant_label, story_example_label, character_assistant_label,"
    " published_at"
    " FROM prompt_sets WHERE status = 'published' AND lane = :lane AND model = :model"
    " ORDER BY published_at DESC LIMIT 1"
)
# 모델 열을 모르는 코드(옛 마이그레이션의 원시 SQL)의 활성 규칙.
_LANE_ONLY_ACTIVE_SET_SQL = sa.text(
    "SELECT id FROM prompt_sets WHERE status = 'published' AND lane = :lane ORDER BY published_at DESC LIMIT 1"
)
_SECTIONS_SQL = sa.text(
    'SELECT channel, scope, slot, variant, body, conditional, "order"'
    " FROM prompt_sections WHERE prompt_set_id = :id"
)
_DRAFT_SQL = sa.text("SELECT id FROM prompt_sets WHERE status = 'draft' AND lane = :lane AND model = :model")
_SWAP_BODY_SQL = sa.text(
    "UPDATE prompt_sections SET body = :to_body"
    " WHERE prompt_set_id = :id AND channel = :channel AND slot = :slot AND body = :from_body"
)


def _assert_recall_row(rows: Sequence[Row], *, what: str) -> None:
    """게시본에 회상 행이 정확히 하나이고 그 본문이 앞 리비전 문안과 바이트로 같은지 본다. 어긋나면 `RuntimeError` — `what` 은
    메시지에 쓸 세트 이름이다."""
    matches = [row for row in rows if row[0] == _GENERATION and row[2] == RECALL_SLOT]
    if len(matches) != 1:
        raise RuntimeError(f"[{what}] {_GENERATION} 채널의 {RECALL_SLOT} 행이 정확히 하나가 아니다({len(matches)}개)")
    if matches[0][4] != OLD_RECALL_BODY:
        raise RuntimeError(
            f"[{what}] {_GENERATION} 채널의 {RECALL_SLOT} 본문이 앞 리비전이 심은 문안과 다르다 — 어드민이 고친 운영 문안을"
            " 덮어쓰지 않는다. 고친 문안과 새 문안을 합친 뒤 다시 배포한다"
        )


def _with_new_recall(rows: Sequence[Row]) -> list[Row]:
    """기존 행 그대로, 회상 본문만 새 문안."""
    return [
        (channel, scope, slot, variant, RECALL_BODY if (channel, slot) == (_GENERATION, RECALL_SLOT) else body, cond, order)
        for channel, scope, slot, variant, body, cond, order in rows
    ]


def _gemini_seed_time(gemini_at: datetime, now: datetime) -> datetime:
    """새 Gemini 세트의 게시 시각 — 레인에서 가장 나중이 되게 `max(now, 원본 + 1초)`."""
    return max(now, gemini_at + timedelta(seconds=1))


def _seed_time(chain_at: datetime, gemini_seed_at: datetime) -> datetime:
    """Gemini 가 아닌 체인의 새 세트 게시 시각 — 그 체인 활성 시각과 그 레인 새 Gemini 세트 시각의 중간값. 사이에 둘 시각이
    없으면 `RuntimeError`."""
    chosen = chain_at + (gemini_seed_at - chain_at) / 2
    if not chain_at < chosen < gemini_seed_at:
        raise RuntimeError(
            f"두 활성 조회 규칙을 함께 만족하는 게시 시각이 없다: 체인 활성 {chain_at}, 새 Gemini 세트 {gemini_seed_at}"
        )
    return chosen


def _section_id(lane: str, model: str, channel: str, scope: str, slot: str, variant: str) -> uuid.UUID:
    return uuid.uuid5(_SECTION_ID_NAMESPACE, f"{lane}:{model}:{channel}:{scope}:{slot}:{variant}")


def _rows_of(conn: Connection, set_id: uuid.UUID) -> list[Row]:
    return [tuple(row) for row in conn.execute(_SECTIONS_SQL, {"id": set_id}).fetchall()]


def _insert_set(
    conn: Connection,
    *,
    lane: str,
    model: str,
    source: sa.Row[tuple[object, ...]],
    published_at: datetime,
    rows: Sequence[Row],
) -> None:
    set_id = NEW_SET_IDS[(lane, model)]
    # `_next_published_version`(admin/prompts.py)과 같은 규칙 — 전 레인·전 모델 대상.
    latest_version = conn.execute(
        sa.text("SELECT max(CAST(version AS INTEGER)) FROM prompt_sets WHERE status = 'published'")
    ).scalar_one()
    conn.execute(
        sa.insert(prompt_sets_table),
        [
            {
                "id": set_id,
                "version": str((latest_version or 0) + 1),
                "status": "published",
                "lane": lane,
                "model": model,
                "user_label": source.user_label,
                "story_assistant_label": source.story_assistant_label,
                "story_example_label": source.story_example_label,
                "character_assistant_label": source.character_assistant_label,
                "note": _NOTE,
                "published_at": published_at,
            }
        ],
    )
    conn.execute(
        sa.insert(prompt_sections_table),
        [
            {
                "id": _section_id(lane, model, channel, scope, slot, variant),
                "prompt_set_id": set_id,
                "channel": channel,
                "scope": scope,
                "slot": slot,
                "variant": variant,
                "body": body,
                "conditional": conditional,
                "order": order,
            }
            for channel, scope, slot, variant, body, conditional, order in rows
        ],
    )


def seed_published_sets(conn: Connection) -> None:
    """레인마다 글을 쓰는 세 체인에 새 세트를 넣고, 두 활성 조회 규칙으로 다시 확인한다.

    `op` 를 쓰지 않는다 — 테스트가 롤백되는 세션의 커넥션에 `run_sync` 로 부르기 위해서다."""
    existing = conn.execute(
        sa.select(sa.func.count()).select_from(prompt_sets_table).where(
            prompt_sets_table.c.id.in_(list(NEW_SET_IDS.values()))
        )
    ).scalar_one()
    if existing:
        raise RuntimeError(f"이 리비전의 세트가 이미 있다({existing}개)")
    for lane in _LANES:
        sources = {model: conn.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": model}).one() for model in _MODELS}
        lane_only = conn.execute(_LANE_ONLY_ACTIVE_SET_SQL, {"lane": lane}).one().id
        if lane_only != sources[_GEMINI].id:
            raise RuntimeError(
                f"[{lane}] 레인만 보는 활성 조회가 이미 Gemini 세트가 아닌 {lane_only} 를 집는다 — 두 활성 조회 규칙을 함께"
                " 만족하는 게시 시각이 없다"
            )
        # 넣기 전에 세 체인을 모두 검사한다 — 하나라도 어긋나면 그 레인에는 아무것도 넣지 않은 채 멈춘다.
        source_rows = {model: _rows_of(conn, sources[model].id) for model in _MODELS}
        for model in _MODELS:
            _assert_recall_row(source_rows[model], what=f"{lane}/{model}")

        gemini_seed_at = _gemini_seed_time(sources[_GEMINI].published_at, datetime.now(UTC))
        for model in _MODELS:
            _insert_set(
                conn,
                lane=lane,
                model=model,
                source=sources[model],
                published_at=(
                    gemini_seed_at if model == _GEMINI else _seed_time(sources[model].published_at, gemini_seed_at)
                ),
                rows=_with_new_recall(source_rows[model]),
            )

        for model in _MODELS:
            chosen = conn.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": model}).one().id
            if chosen != NEW_SET_IDS[(lane, model)]:
                raise RuntimeError(
                    f"[{lane}/{model}] 새 세트가 활성으로 뽑히지 않는다: 활성={chosen}, 새 세트={NEW_SET_IDS[(lane, model)]}"
                )
        lane_only_after = conn.execute(_LANE_ONLY_ACTIVE_SET_SQL, {"lane": lane}).one().id
        if lane_only_after != NEW_SET_IDS[(lane, _GEMINI)]:
            raise RuntimeError(f"[{lane}] 레인만 보는 활성 조회가 새 Gemini 세트를 집지 않는다: {lane_only_after}")


def _swap_draft_recall(conn: Connection, *, from_body: str, to_body: str) -> list[tuple[str, str]]:
    """글을 쓰는 체인의 초안에서 회상 본문이 `from_body` 와 같으면 `to_body` 로 바꾸고, 바꾼 (레인, 모델) 목록을 돌려준다."""
    swapped: list[tuple[str, str]] = []
    for lane in _LANES:
        for model in _MODELS:
            draft_id = conn.execute(_DRAFT_SQL, {"lane": lane, "model": model}).scalar_one_or_none()
            if draft_id is None:
                continue
            result = conn.execute(
                _SWAP_BODY_SQL,
                {
                    "id": draft_id,
                    "channel": _GENERATION,
                    "slot": RECALL_SLOT,
                    "from_body": from_body,
                    "to_body": to_body,
                },
            )
            if result.rowcount:
                swapped.append((lane, model))
    return swapped


def _patch_drafts(conn: Connection) -> list[tuple[str, str]]:
    """초안의 회상 본문이 앞 리비전 문안과 같으면 새 문안으로 바꾼다(위 docstring). `op` 를 쓰지 않는 이유는
    `seed_published_sets` 와 같다."""
    return _swap_draft_recall(conn, from_body=OLD_RECALL_BODY, to_body=RECALL_BODY)


def _delete_draft_rows(conn: Connection) -> list[tuple[str, str]]:
    """초안의 회상 본문이 이 리비전의 새 문안이면 옛 문안으로 되돌린다."""
    return _swap_draft_recall(conn, from_body=RECALL_BODY, to_body=OLD_RECALL_BODY)


def upgrade() -> None:
    """Upgrade schema."""
    # 배포 중에도 떠 있는 API 가 prompt_sets 를 읽고 쓴다. 이 리비전은 행만 넣고 초안 몇 행만 고쳐 오래 쥐는 락이 없지만, 다른
    # 트랜잭션 뒤에서 끝없이 기다리지 않고 5초 안에 실패해 배포가 멈추게 첫 문장으로 건다.
    op.execute("SET LOCAL lock_timeout = '5s'")
    bind = op.get_bind()
    seed_published_sets(bind)
    _patch_drafts(bind)


def delete_seeded_rows(conn: Connection) -> None:
    """위 docstring 의 `downgrade()`. `op` 를 쓰지 않는 이유는 `seed_published_sets` 와 같다."""
    later: list[str] = []
    for (lane, model), seed_id in NEW_SET_IDS.items():
        count = conn.execute(
            sa.text(
                "SELECT count(*) FROM prompt_sets WHERE status = 'published' AND lane = :lane AND model = :model"
                " AND id <> :seed AND published_at > (SELECT published_at FROM prompt_sets WHERE id = :seed)"
            ),
            {"lane": lane, "model": model, "seed": seed_id},
        ).scalar_one()
        if count:
            later.append(f"{lane}/{model} {count}개")
    if later:
        raise RuntimeError(
            f"시드 뒤에 어드민이 게시한 세트가 있다({', '.join(later)}) — 되돌려도 그 세트가 활성으로 남는다. 아무것도 지우지"
            " 않았다"
        )

    seed_ids = list(NEW_SET_IDS.values())
    conn.execute(sa.delete(prompt_sections_table).where(prompt_sections_table.c.prompt_set_id.in_(seed_ids)))
    conn.execute(sa.delete(prompt_sets_table).where(prompt_sets_table.c.id.in_(seed_ids)))
    _delete_draft_rows(conn)


def downgrade() -> None:
    """Downgrade schema."""
    delete_seeded_rows(op.get_bind())
