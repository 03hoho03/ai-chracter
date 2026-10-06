"""prompt sets model chains

Revision ID: e6aa289fea62
Revises: a966fc016bf1
Create Date: 2026-10-06 12:00:00.000000

프롬프트 세트에 글쓰기 모델 축(`prompt_sets.model`)을 더하고, story·character 레인에 Claude Sonnet·Opus 용 published
세트 4개를 심는다. 레인 × 모델마다 초안·게시·복원·활성 판정이 따로 가는 독립 버전 체인이 된다.

**열**: `model` Text NOT NULL, `server_default 'gemini'`. `add_column` 이 기존 행을 전부 `'gemini'` 로 채운다. 기본값은
떼지 않는다 — 이 열을 모르는 옛 이미지로 되돌린 동안 어드민이 게시한 행도 Gemini 체인에 들어가야 해서다.

**인덱스**: 초안 유니크 `(lane)` → `(lane, model)`, 게시 버전 유니크 `(lane, version)` → `(lane, model, version)`(이름도
바꾼다), 활성 조회용 `(lane, published_at desc)` → `(lane, model, published_at desc)`.

**시드**: (story, character) × (sonnet, opus) 를 이 순서로 돈다. 원본은 그 레인의 **Gemini** 활성 세트다(활성 SELECT 에
모델 필터가 있다). 원본의 `system`·`generation` 채널 행만 바이트·order 그대로 복사하고 라벨 4개도 복사한다. 판정·요약·
소설화 채널은 넣지 않는다 — 그 호출은 고른 모델과 무관하게 Gemini 세트를 읽는다.
- 세트 id 는 리터럴 `NEW_SET_IDS`, 섹션 id 는 새 namespace 의 `uuid5("{lane}:{model}:{channel}:{scope}:{slot}:{variant}")`.
- `version` 은 전 레인·전 모델 published 최대 + 1 을 차례로 매긴다(어드민 게시와 같은 규칙).
- **초안은 심지 않는다.** 어드민의 초안 조회는 초안이 없으면 활성 세트 사본을 돌려주므로 초안이 필요 없다. 그리고 레인에
  초안이 둘 이상 생기면 레인만 보고 초안을 한 행으로 읽는 코드가 깨진다 — 옛 마이그레이션의 초안 보정 헬퍼와 그 테스트,
  옛 이미지의 어드민 초안 조회가 그렇다.

**`published_at` 은 원본보다 1초 과거다.** 앞선 시드 리비전들은 새 세트가 활성이 되도록 `max(now, 원본 + 1초)` 를 썼지만
여기서는 반대로 둔다. 모델 열을 모르는 코드(옛 이미지, 옛 마이그레이션의 원시 SQL)는 레인만 보고 `published_at` 이 가장
최신인 게시본을 활성으로 고른다. Claude 세트가 원본보다 나중이면 그 코드가 판정·요약 채널이 없는 Claude 세트를 활성으로
집어 채팅 판정·요약이 깨진다. 1초 과거면 그 코드는 계속 Gemini 세트를 집고, 모델로 거르는 새 코드는 (레인, 모델)마다 한
세트뿐이라 시각과 무관하게 Claude 세트를 집는다. 삽입 뒤 두 규칙으로 다시 SELECT 해 이 두 사실을 확인한다(Gemini 활성
id 불변 포함).

**가정이 어긋나면 배포를 멈춘다**(`_assert_layout`, `RuntimeError`): 원본에 `system`·`generation` 채널 행이 없거나, 그
(레인, 모델)에 이미 세트(초안이든 게시본이든)가 있을 때. 체인이 한 트랜잭션이라 앞 스키마 변경도 함께 롤백된다.

⚠️ **운영 메모**:
- 앞으로 슬롯을 더하는 마이그레이션은 Gemini 두 레인뿐 아니라 Claude 체인 4개(최대 6개 체인)를 다룰지 따로 판단한다.
  Claude 세트는 `system`·`generation` 만 가지므로 그 두 채널의 슬롯이면 Claude 체인에도 넣어야 게시 검증의 슬롯 집합이
  맞는다.
- 마이그레이션은 활성 세트 캐시를 지우지 않는다. 캐시 키 형식이 이 변경과 함께 모델을 포함하는 형식으로 바뀌어 새 코드는
  옛 키를 읽지 않으므로 영향이 없다.
- 앞으로 활성·초안 세트를 원시 SQL 로 고르는 마이그레이션은 반드시 모델로 거른다(`AND model = 'gemini'` 또는 대상 모델).
  레인만 보는 조회는 Claude 세트를 집을 수 있고, 초안을 한 행으로 읽으면 레인에 초안이 둘 이상일 때 `MultipleResultsFound`
  로 깨진다.
- `upgrade()` 는 첫 문장으로 `SET LOCAL lock_timeout = '5s'` 를 건다. 배포 중에도 떠 있는 API 가 `prompt_sets` 를 읽으므로
  `ALTER TABLE` 이 오래 걸린 트랜잭션 뒤에서 락을 기다리면 그 뒤로 모든 읽기가 줄을 선다. 5초 안에 락을 못 잡으면 마이그레이션이
  실패해 배포가 멈추고(체인 전체 롤백), 다시 돌리면 된다. `SET LOCAL` 은 트랜잭션 끝까지 유효해 같은 실행에서 뒤따르는
  리비전에도 걸린다.

**롤백**: Claude 행을 어드민에서 새로 만들지 않았다면 이미지만 되돌려도 안전하다(위 `published_at`·초안 미시드 덕분).
만들었다면 이미지를 되돌리기 **전에** `model <> 'gemini'` 인 섹션과 세트를 지우되 `NEW_SET_IDS` 의 시드 4개는 남긴다.
시드까지 지우면 나중에 새 이미지를 다시 올릴 때 `alembic upgrade head` 가 이미 적용된 이 리비전을 건너뛰어 Claude 체인이
빈 채로 남는다(초안 조회 500, 상위 모델 턴 실패). 시드는 남겨도 옛 코드에 안전하다 — `published_at` 이 원본 Gemini 세트보다
1초 과거라 레인만 보는 "최신 게시본" 조회가 집지 않고, 초안이 아니라 초안 조회에도 걸리지 않는다.

`downgrade()`: `model <> 'gemini'` 인 **모든** 세트를 섹션 → 세트 순으로 지운다(FK 에 cascade 가 없다). 리터럴 id 만
지우면 어드민이 만든 Claude 초안·게시본이 남은 채 열이 사라져, 그 행이 레인의 초안 유니크를 깨거나 레인의 최신 게시본이
된다. 그다음 인덱스를 되돌리고 열을 지운다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 테스트(`tests/test_prompt_model_sets_migration.py`)가 이 모듈을
`importlib` 로 불러 순수 함수와 `_delete_non_gemini_sets` 를 직접 부른다.
"""
import uuid
from collections.abc import Sequence
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e6aa289fea62'
down_revision: str | Sequence[str] | None = 'a966fc016bf1'
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
_MODELS: tuple[str, ...] = ("sonnet", "opus")
CHANNELS: tuple[str, ...] = ("system", "generation")

# 리터럴 UUID — 작성 시점에 uuid.uuid4()를 한 번씩 실행해 뽑았다.
NEW_SET_IDS: dict[tuple[str, str], uuid.UUID] = {
    ("story", "sonnet"): uuid.UUID('ba2a926c-e9ed-46e0-b42c-9c21c63552f6'),
    ("story", "opus"): uuid.UUID('f3237e56-5ff6-4b27-9135-98495c0094bb'),
    ("character", "sonnet"): uuid.UUID('b9c2f1ec-5e8c-48ce-8fc9-ffefdc6950d2'),
    ("character", "opus"): uuid.UUID('9b308ef1-bdb9-4f23-a2d8-fb6ae6ad778c'),
}
_SECTION_ID_NAMESPACE = uuid.UUID('183bf557-8956-46b1-ab7a-abb3814330c7')

_NOTES: dict[str, str] = {
    "sonnet": "Claude Sonnet 세트 첫 버전(Gemini 활성 세트의 system·generation 사본)",
    "opus": "Claude Opus 세트 첫 버전(Gemini 활성 세트의 system·generation 사본)",
}

# 모델 열이 생긴 뒤의 활성 규칙 — `load_active_prompt_set`(chat/prompt_builder.py)과 같다.
_ACTIVE_SET_SQL = sa.text(
    "SELECT id, user_label, story_assistant_label, story_example_label, character_assistant_label,"
    " published_at"
    " FROM prompt_sets WHERE status = 'published' AND lane = :lane AND model = :model"
    " ORDER BY published_at DESC LIMIT 1"
)
# 모델 열을 모르는 코드(옛 이미지·옛 마이그레이션)의 활성 규칙.
_LANE_ONLY_ACTIVE_SET_SQL = sa.text(
    "SELECT id FROM prompt_sets WHERE status = 'published' AND lane = :lane ORDER BY published_at DESC LIMIT 1"
)
_SECTIONS_SQL = sa.text(
    'SELECT channel, scope, slot, variant, body, conditional, "order"'
    " FROM prompt_sections WHERE prompt_set_id = :id"
)
_EXISTING_SETS_SQL = sa.text("SELECT count(*) FROM prompt_sets WHERE lane = :lane AND model = :model")

Row = tuple[str, str, str, str, str, bool, int]


def _assert_layout(source_rows: Sequence[Row], existing_set_count: int, *, lane: str, model: str) -> None:
    """원본에 복사할 채널 행이 하나라도 없거나, 그 (레인, 모델)에 이미 세트가 있으면 `RuntimeError`(배포를 멈춘다)."""
    if existing_set_count:
        raise RuntimeError(f"[{lane}/{model}] 이미 세트가 {existing_set_count}개 있다")
    missing = sorted(set(CHANNELS) - {row[0] for row in source_rows})
    if missing:
        raise RuntimeError(f"[{lane}/{model}] 원본 Gemini 세트에 채널이 없다 — 누락 {missing}")


def _copied_rows(source_rows: Sequence[Row]) -> list[Row]:
    """원본 행 중 Claude 세트로 복사할 것 — `CHANNELS` 의 행만, 순서·값 그대로."""
    return [row for row in source_rows if row[0] in CHANNELS]


def _section_id(lane: str, model: str, channel: str, scope: str, slot: str, variant: str) -> uuid.UUID:
    return uuid.uuid5(_SECTION_ID_NAMESPACE, f"{lane}:{model}:{channel}:{scope}:{slot}:{variant}")


def _section_dicts(rows: Sequence[Row], *, lane: str, model: str, set_id: uuid.UUID) -> list[dict[str, object]]:
    return [
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
    ]


def _delete_non_gemini_sets(conn: Connection) -> None:
    """Gemini 가 아닌 세트 전부(이 리비전이 심은 것 + 어드민이 만든 초안·게시본)를 섹션 → 세트 순으로 지운다.

    `op` 를 쓰지 않는다 — 테스트가 롤백되는 세션의 커넥션에 `run_sync` 로 부르기 위해서다."""
    conn.execute(
        sa.text(
            "DELETE FROM prompt_sections WHERE prompt_set_id IN (SELECT id FROM prompt_sets WHERE model <> 'gemini')"
        )
    )
    conn.execute(sa.text("DELETE FROM prompt_sets WHERE model <> 'gemini'"))


def upgrade() -> None:
    """Upgrade schema."""
    # 떠 있는 API 의 prompt_sets 읽기가 ALTER 의 락 대기 뒤로 줄서지 않게 — 위 docstring 운영 메모.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("prompt_sets", sa.Column("model", sa.Text(), server_default="gemini", nullable=False))

    op.drop_index("ix_prompt_sets_draft", table_name="prompt_sets", postgresql_where=sa.text("status = 'draft'"))
    op.create_index(
        "ix_prompt_sets_draft", "prompt_sets", ["lane", "model"], unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.drop_index(
        "ix_prompt_sets_lane_version_published", table_name="prompt_sets",
        postgresql_where=sa.text("status = 'published'"),
    )
    op.create_index(
        "ix_prompt_sets_lane_model_version_published", "prompt_sets", ["lane", "model", "version"], unique=True,
        postgresql_where=sa.text("status = 'published'"),
    )
    op.drop_index("ix_prompt_sets_lane_published_at", table_name="prompt_sets")
    op.create_index(
        "ix_prompt_sets_lane_model_published_at", "prompt_sets",
        ["lane", "model", sa.literal_column("published_at DESC")], unique=False,
    )

    bind = op.get_bind()
    for lane in _LANES:
        source = bind.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": "gemini"}).one()
        source_rows: list[Row] = [tuple(row) for row in bind.execute(_SECTIONS_SQL, {"id": source.id}).fetchall()]
        for model in _MODELS:
            set_id = NEW_SET_IDS[(lane, model)]
            existing = bind.execute(_EXISTING_SETS_SQL, {"lane": lane, "model": model}).scalar_one()
            _assert_layout(source_rows, existing, lane=lane, model=model)

            # `_next_published_version`(admin/prompts.py)과 같은 규칙 — 전 레인·전 모델 대상.
            latest_version = bind.execute(
                sa.text("SELECT max(CAST(version AS INTEGER)) FROM prompt_sets WHERE status = 'published'")
            ).scalar_one()
            op.bulk_insert(
                prompt_sets_table,
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
                        "note": _NOTES[model],
                        # 원본보다 과거 — 위 docstring.
                        "published_at": source.published_at - timedelta(seconds=1),
                    }
                ],
            )
            op.bulk_insert(
                prompt_sections_table,
                _section_dicts(_copied_rows(source_rows), lane=lane, model=model, set_id=set_id),
            )

            chosen = bind.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": model}).one().id
            if chosen != set_id:
                raise RuntimeError(f"[{lane}/{model}] 새 세트가 활성으로 뽑히지 않는다: 활성={chosen}, 새 세트={set_id}")

        gemini_active = bind.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": "gemini"}).one().id
        lane_only_active = bind.execute(_LANE_ONLY_ACTIVE_SET_SQL, {"lane": lane}).one().id
        if gemini_active != source.id or lane_only_active != source.id:
            raise RuntimeError(
                f"[{lane}] Gemini 활성 세트가 바뀌었다: 원본={source.id}, 모델 필터={gemini_active},"
                f" 레인만={lane_only_active}"
            )


def downgrade() -> None:
    """Downgrade schema."""
    _delete_non_gemini_sets(op.get_bind())

    op.drop_index("ix_prompt_sets_lane_model_published_at", table_name="prompt_sets")
    op.create_index(
        "ix_prompt_sets_lane_published_at", "prompt_sets",
        ["lane", sa.literal_column("published_at DESC")], unique=False,
    )
    op.drop_index(
        "ix_prompt_sets_lane_model_version_published", table_name="prompt_sets",
        postgresql_where=sa.text("status = 'published'"),
    )
    op.create_index(
        "ix_prompt_sets_lane_version_published", "prompt_sets", ["lane", "version"], unique=True,
        postgresql_where=sa.text("status = 'published'"),
    )
    op.drop_index("ix_prompt_sets_draft", table_name="prompt_sets", postgresql_where=sa.text("status = 'draft'"))
    op.create_index(
        "ix_prompt_sets_draft", "prompt_sets", ["lane"], unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.drop_column("prompt_sets", "model")
