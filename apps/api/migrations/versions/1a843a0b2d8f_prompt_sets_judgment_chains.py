"""prompt sets judgment chains

Revision ID: 1a843a0b2d8f
Revises: 42ba15156c84
Create Date: 2026-10-10 20:00:00.000000

채팅 판정·요약 문안을 Gemini 가 아닌 체인에도 둔다. 판정(스탯 규칙·엔딩·그림)과 기억 요약을 다른 모델로 돌릴 수 있게 하기
위한 문안 데이터다 — 이 리비전만으로는 어떤 호출도 이 행을 읽지 않는다(판정·요약은 계속 Gemini 세트를 읽는다).

**심는 것**: story·character 레인마다 세 세트.
- **Claude 체인(sonnet·opus)**: 그 체인 활성 세트(라벨 포함)를 바이트 그대로 복사하고, 그 레인 Gemini 활성 세트의 판정·
  요약 채널 행을 바이트·order 그대로 더한 **새 published 세트**. 생성 채널 행은 그 체인 것 그대로라 생성 문안은 이 리비전
  전과 같다.
- **판정 전용 체인(haiku)**: 그 레인 Gemini 활성 세트의 라벨과 판정·요약 채널 행만 가진 새 체인의 첫 세트. 그 id 로는 글을
  쓰지 않아 생성 채널이 없다.
- 판정·요약 채널은 story 가 `stat_rule_judgment`·`ending_judgment`·`image_judgment`·`memory_summary`, character 가
  `image_judgment`·`memory_summary` 다. 옛 `stat_judgment` 채널은 읽는 코드가 없어 넣지 않고, 소설화 채널도 넣지 않는다.
- 세트 id 는 리터럴 `NEW_SET_IDS`, 섹션 id 는 새 namespace 의 `uuid5("{lane}:{model}:{channel}:{scope}:{slot}:{variant}")`
  (초안 행은 `draft:` 접두). `version` 은 전 레인·전 모델 published 최대 + 1 을 (story, character) × (sonnet, opus,
  haiku) 순서로 매긴다(어드민 게시와 같은 규칙). 판정 전용 체인에는 초안을 심지 않는다 — 초안 조회는 초안이 없으면 활성 세트
  사본을 돌려준다.

**게시된 세트는 고치지 않는다** — 기존 세트에 행을 끼워 넣지 않고 새 세트를 만든다. 그래서 이 리비전 이전의 Claude 버전은
복원은 되지만 게시 검증("누락")에 막힌다(제약으로 받아들인다).

**`published_at` — 두 활성 조회 규칙을 함께 만족시킨다.**
- 모델로 거르는 조회(`load_active_prompt_set`)는 (레인, 모델)마다 최신 게시본을 고른다 — 새 Claude 세트가 그 체인의 기존
  활성 세트보다 나중이어야 한다.
- 레인만 보는 조회(모델 열을 모르는 옛 이미지·옛 마이그레이션의 원시 SQL)는 레인의 최신 게시본을 고른다 — 새 세트가 모두 그
  레인 Gemini 활성 세트보다 과거여야 계속 Gemini 세트를 집는다.
- 그래서 Claude 새 세트는 (그 체인 활성 시각, 그 레인 Gemini 활성 시각) 사이의 **중간값**이다. 모델 축 리비전이 Claude 세트를
  "Gemini − 1초"로 심었고 그 뒤 character Gemini 세트를 새로 게시한 일이 없으면 character 레인의 창이 정확히 1초라, 그 리비전처럼
  "Gemini − 1초"를 쓰면 기존 Claude 세트와 시각이 같아져 모델로 거르는 조회가 동률(어느 쪽을 집을지 정해지지 않음)이 된다.
  중간값은 양 끝과 0.5초씩 떨어진다. 사이에 둘 시각이 없으면(어드민이 Claude 체인을 Gemini 보다 나중에 게시해 레인만 보는
  조회가 이미 Claude 를 집고 있으면) `RuntimeError` 로 배포를 멈춘다 — 그때는 사람이 판단한다.
- 판정 전용 세트는 그 체인에 하나뿐이라 레인만 보는 조회만 만족하면 된다 — Gemini 활성 − 1초.
- 시각은 이 리비전이 도는 순간 DB 에서 다시 읽어 계산한다(배포 전에 어드민이 게시하면 창이 바뀐다). 삽입 뒤 두 규칙으로 다시
  SELECT 해 확인한다: 여섯 체인 활성이 새 세트, Gemini 활성 불변, 레인만 보는 활성 == Gemini 활성. 어긋나면 `RuntimeError`.

**가정이 어긋나면 배포를 멈춘다**(`RuntimeError`, 체인이 한 트랜잭션이라 앞 리비전까지 함께 롤백된다): Gemini 활성 세트에 그
레인 판정·요약 채널이 하나라도 없을 때, Claude 활성 세트에 생성 채널이 없거나 판정·요약 채널 행이 이미 있을 때, 그 레인에
판정 전용 세트가 이미 있을 때(초안 포함), Claude 초안에 판정·요약 채널 행이 이미 있을 때.

**초안**: story·character × sonnet·opus 초안이 있으면 그 초안에도 같은 행을 제자리에서 넣는다(`_patch_drafts`). 다른 행은
건드리지 않는다.

**옛 이미지가 이 데이터 위에서 도는 구간**(배포 중 겹침, 이미지만 되돌린 동안): 옛 코드는 Claude 세트에서 생성 채널만 렌더하므로
생성 글은 그대로고, 판정·요약은 Gemini 세트를 읽어 그대로다. 옛 코드의 어드민 게시 검증은 새 Claude 세트·초안의 판정·요약 행을
"잉여"로 거부해 **Claude 체인의 어드민 게시만** 막힌다. 판정 전용 세트는 옛 코드가 목록·조회 어디에도 보이지 않는다.

⚠️ **운영 메모**:
- 마이그레이션은 활성 세트 캐시를 지우지 않는다 — 배포 직후 최대 300초 동안 옛 Claude 세트로 렌더할 수 있지만 생성 행이
  바이트 사본이라 같은 글이고, 판정은 여전히 Gemini 세트를 읽는다.
- 배포 전부터 열어 둔 어드민 프롬프트 편집 탭에서 저장하면 초안이 섹션 전체 교체로 새 행을 잃고 게시가 "누락"으로 막힌다.
  **배포 뒤에는 편집 탭을 새로고침한다.**
- **앞으로 판정·요약 슬롯을 더하거나 바꾸는 마이그레이션은 Gemini 체인뿐 아니라 Claude 체인(story·character × sonnet·opus)과
  판정 전용 체인(story·character × haiku)도 다룬다** — 그 체인 게시 검증의 슬롯 집합이 그 채널을 포함하기 때문이다. 판정 전용
  id 를 하나 더하면 그 id 의 체인 둘을 심는 리비전과 함께 이 목록이 는다.
- 🔴 **시드를 손으로 지우지 않는다.** 지우면 다시 배포할 때 `alembic upgrade head` 가 이미 적용된 이 리비전을 건너뛰어 판정 전용
  체인이 빈 채로 남고(어드민 초안 조회 500), Claude 체인은 판정·요약 행이 없는 이전 세트로 돌아가 새 코드의 Claude 게시가
  "누락"으로 막힌다. 되돌리려면 아래 `downgrade` 를 쓴다.
- 🔴 **프롬프트 옛 버전을 통째로 복원하지 않는다.** 이 리비전 이전 Claude 버전은 판정·요약 행이 없어 새 코드에서 게시가 막히고,
  옛 이미지에서 복원·게시하면 판정·요약 행이 사라진다 — 현재 활성본에서 바뀐 섹션만 고친다.

**롤백 순서**: ① 판정을 Gemini 가 아닌 모델로 돌리는 설정이 있으면 전부 Gemini 로 되돌렸는지 확인한다(이 리비전 시점에는 그런
설정이 아직 없어 늘 참이다) → ② 1순위는 이미지만 되돌리기(위 겹침 구간과 같은 상태 — 막히는 것은 Claude 체인 어드민 게시뿐)
→ ③ `downgrade` 가 필요하면 **새 이미지로** 실행한 뒤 이미지를 되돌린다.

`downgrade()`(`delete_seeded_rows`): 시드 뒤에 어드민이 Claude 체인(sonnet·opus)에 새 버전을 게시했으면 아무것도 지우지 않고
`RuntimeError` 로 멈춘다 — 그 게시본에도 판정·요약 행이 있어 되돌린 뒤 활성으로 남으면 이전 코드의 게시 검증이 그 체인을 막고,
푸는 길이 옛 버전 통째 복원뿐이라 사람이 판단해야 한다. 없으면 리터럴 Claude 시드의 섹션 → 세트, **판정 전용 세트 전부**(시드와
어드민이 만든 초안·게시본 — 이전 코드는 그 체인을 다룰 수 없고, 남기면 다시 올릴 때 "이미 세트가 있다"로 막힌다), Claude 초안의
판정·요약 채널 행(PK 가 아니라 레인·모델·채널로 찾는다 — 초안 저장이 섹션을 통째로 교체해 PK 가 바뀌어 있을 수 있다)을 지운다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 테스트(`tests/test_prompt_judgment_chains_migration.py`)가 이 모듈을
`importlib` 로 불러 순수 함수와 `seed_published_sets`·`_patch_drafts`·`delete_seeded_rows` 를 직접 부른다.
"""
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1a843a0b2d8f'
down_revision: str | Sequence[str] | None = '42ba15156c84'
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
_CLAUDE_MODELS: tuple[str, ...] = ("sonnet", "opus")
_JUDGMENT_ONLY_MODEL = "haiku"
_GENERATION_CHANNELS: tuple[str, ...] = ("system", "generation")
# 레인마다 판정·요약 호출이 읽는 채널. 어드민 게시 검증의 같은 표(`admin/prompts.py`)와 짝이다 — 이 파일은 `api.*` 를
# import 하지 않아 리터럴로 둔다. 둘이 맞는지는 시드 세트가 게시 검증을 통과하는지로 테스트가 본다.
JUDGMENT_CHANNELS: dict[str, tuple[str, ...]] = {
    "story": ("stat_rule_judgment", "ending_judgment", "image_judgment", "memory_summary"),
    "character": ("image_judgment", "memory_summary"),
}

# 리터럴 UUID — 작성 시점에 uuid.uuid4()를 한 번씩 실행해 뽑았다.
NEW_SET_IDS: dict[tuple[str, str], uuid.UUID] = {
    ("story", "sonnet"): uuid.UUID('32b99025-22e8-45fa-86a5-50f267b30a1b'),
    ("story", "opus"): uuid.UUID('73026fdc-e2bc-4e99-9b94-950f791d6835'),
    ("story", "haiku"): uuid.UUID('e8685db5-f431-419a-9957-0db6b27ec848'),
    ("character", "sonnet"): uuid.UUID('b483d5c3-92dd-4dd9-ad4b-9ae6488bbcb4'),
    ("character", "opus"): uuid.UUID('9a2b4dbb-ff70-4ccf-a8b3-4cff6ca785c0'),
    ("character", "haiku"): uuid.UUID('8114a6d6-b5cc-4b4a-b8ac-a8f1c25b640d'),
}
_SECTION_ID_NAMESPACE = uuid.UUID('b3806e26-6dae-470a-ab0c-54887863e492')

# 적용된 뒤에는 DB에 영구히 남는 값이라 문서명·번호를 넣지 않는다.
_NOTES: dict[str, str] = {
    "sonnet": "판정·요약 채널 추가(Gemini 활성 세트의 판정·요약 행 사본)",
    "opus": "판정·요약 채널 추가(Gemini 활성 세트의 판정·요약 행 사본)",
    "haiku": "판정 전용 체인 첫 버전(Gemini 활성 세트의 판정·요약 행 사본)",
}

# 모델로 거르는 활성 규칙 — `load_active_prompt_set`(chat/prompt_builder.py)과 같다.
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
_DRAFT_SQL = sa.text("SELECT id FROM prompt_sets WHERE status = 'draft' AND lane = :lane AND model = :model")

Row = tuple[str, str, str, str, str, bool, int]


def _assert_gemini_source(channels: Sequence[str], *, lane: str) -> None:
    """복사할 판정·요약 채널이 Gemini 활성 세트에 하나라도 없으면 `RuntimeError`."""
    missing = sorted(set(JUDGMENT_CHANNELS[lane]) - set(channels))
    if missing:
        raise RuntimeError(f"[{lane}/gemini] 활성 세트에 판정·요약 채널이 없다 — 누락 {missing}")


def _assert_no_judgment_rows(channels: Sequence[str], *, lane: str, what: str) -> None:
    """판정·요약 채널 행이 이미 있으면 두 번 적용되는 것이라 `RuntimeError`. `what` 은 메시지에 쓸 세트 이름이다."""
    present = sorted(set(JUDGMENT_CHANNELS[lane]) & set(channels))
    if present:
        raise RuntimeError(f"[{what}] 판정·요약 채널 행이 이미 있다: {present}")


def _assert_claude_source(channels: Sequence[str], *, lane: str, what: str) -> None:
    """Claude 활성 세트에 생성 채널이 없거나 판정·요약 채널 행이 이미 있으면 `RuntimeError`."""
    missing = sorted(set(_GENERATION_CHANNELS) - set(channels))
    if missing:
        raise RuntimeError(f"[{what}] 활성 세트에 생성 채널이 없다 — 누락 {missing}")
    _assert_no_judgment_rows(channels, lane=lane, what=what)


def _assert_no_judgment_only_sets(existing_set_count: int, *, lane: str) -> None:
    if existing_set_count:
        raise RuntimeError(f"[{lane}/{_JUDGMENT_ONLY_MODEL}] 이미 세트가 {existing_set_count}개 있다")


def _seed_time(claude_at: datetime, gemini_at: datetime) -> datetime:
    """Claude 새 세트의 게시 시각 — 그 체인 활성 시각과 그 레인 Gemini 활성 시각의 중간값(위 docstring). 사이에 둘 시각이
    없으면 `RuntimeError`."""
    chosen = claude_at + (gemini_at - claude_at) / 2
    if not claude_at < chosen < gemini_at:
        raise RuntimeError(
            f"두 활성 조회 규칙을 함께 만족하는 게시 시각이 없다: Claude 활성 {claude_at}, Gemini 활성 {gemini_at}"
        )
    return chosen


def _judgment_rows(rows: Sequence[Row], *, lane: str) -> list[Row]:
    """Gemini 활성 세트 행 중 그 레인 판정·요약 채널 행만, 값 그대로."""
    return [row for row in rows if row[0] in JUDGMENT_CHANNELS[lane]]


def _section_id(prefix: str, lane: str, model: str, channel: str, scope: str, slot: str, variant: str) -> uuid.UUID:
    return uuid.uuid5(_SECTION_ID_NAMESPACE, f"{prefix}{lane}:{model}:{channel}:{scope}:{slot}:{variant}")


def _section_dicts(
    rows: Sequence[Row], *, prefix: str, lane: str, model: str, set_id: uuid.UUID
) -> list[dict[str, object]]:
    return [
        {
            "id": _section_id(prefix, lane, model, channel, scope, slot, variant),
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


def _rows_of(conn: Connection, set_id: uuid.UUID) -> list[Row]:
    return [tuple(row) for row in conn.execute(_SECTIONS_SQL, {"id": set_id}).fetchall()]


def _insert_set(
    conn: Connection,
    *,
    lane: str,
    model: str,
    labels_from: sa.Row[tuple[object, ...]],
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
                "user_label": labels_from.user_label,
                "story_assistant_label": labels_from.story_assistant_label,
                "story_example_label": labels_from.story_example_label,
                "character_assistant_label": labels_from.character_assistant_label,
                "note": _NOTES[model],
                "published_at": published_at,
            }
        ],
    )
    conn.execute(sa.insert(prompt_sections_table), _section_dicts(rows, prefix="", lane=lane, model=model, set_id=set_id))


def seed_published_sets(conn: Connection) -> None:
    """레인마다 Claude 체인 둘과 판정 전용 체인 하나에 새 세트를 넣고, 두 활성 조회 규칙으로 다시 확인한다.

    `op` 를 쓰지 않는다 — 테스트가 롤백되는 세션의 커넥션에 `run_sync` 로 부르기 위해서다."""
    for lane in _LANES:
        gemini = conn.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": "gemini"}).one()
        gemini_rows = _rows_of(conn, gemini.id)
        _assert_gemini_source([row[0] for row in gemini_rows], lane=lane)
        existing = conn.execute(_EXISTING_SETS_SQL, {"lane": lane, "model": _JUDGMENT_ONLY_MODEL}).scalar_one()
        _assert_no_judgment_only_sets(existing, lane=lane)
        lane_only = conn.execute(_LANE_ONLY_ACTIVE_SET_SQL, {"lane": lane}).one().id
        if lane_only != gemini.id:
            raise RuntimeError(
                f"[{lane}] 레인만 보는 활성 조회가 이미 Gemini 세트가 아닌 {lane_only} 를 집는다 — 두 활성 조회 규칙을 함께"
                " 만족하는 게시 시각이 없다"
            )
        judgment = _judgment_rows(gemini_rows, lane=lane)

        for model in _CLAUDE_MODELS:
            claude = conn.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": model}).one()
            claude_rows = _rows_of(conn, claude.id)
            _assert_claude_source([row[0] for row in claude_rows], lane=lane, what=f"{lane}/{model}")
            _insert_set(
                conn,
                lane=lane,
                model=model,
                labels_from=claude,
                published_at=_seed_time(claude.published_at, gemini.published_at),
                rows=[*claude_rows, *judgment],
            )
        _insert_set(
            conn,
            lane=lane,
            model=_JUDGMENT_ONLY_MODEL,
            labels_from=gemini,
            # 그 체인에는 이 세트 하나뿐이라 레인만 보는 조회만 만족하면 된다 — 위 docstring.
            published_at=gemini.published_at - timedelta(seconds=1),
            rows=judgment,
        )

        for model in (*_CLAUDE_MODELS, _JUDGMENT_ONLY_MODEL):
            chosen = conn.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": model}).one().id
            if chosen != NEW_SET_IDS[(lane, model)]:
                raise RuntimeError(
                    f"[{lane}/{model}] 새 세트가 활성으로 뽑히지 않는다: 활성={chosen}, 새 세트={NEW_SET_IDS[(lane, model)]}"
                )
        gemini_after = conn.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": "gemini"}).one().id
        lane_only_after = conn.execute(_LANE_ONLY_ACTIVE_SET_SQL, {"lane": lane}).one().id
        if gemini_after != gemini.id or lane_only_after != gemini.id:
            raise RuntimeError(
                f"[{lane}] Gemini 활성 세트가 바뀌었다: 원본={gemini.id}, 모델 필터={gemini_after}, 레인만={lane_only_after}"
            )


def _patch_drafts(conn: Connection) -> list[tuple[str, str]]:
    """Claude 체인 초안이 있으면 초안 **자신의** 행으로 가정을 검사한 뒤 그 레인 Gemini 활성 세트의 판정·요약 행을 제자리에서
    넣는다. 손댄 (레인, 모델) 목록을 돌려준다. `op` 를 쓰지 않는 이유는 `seed_published_sets` 와 같다."""
    patched: list[tuple[str, str]] = []
    for lane in _LANES:
        gemini = conn.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": "gemini"}).one()
        judgment = _judgment_rows(_rows_of(conn, gemini.id), lane=lane)
        for model in _CLAUDE_MODELS:
            draft_id = conn.execute(_DRAFT_SQL, {"lane": lane, "model": model}).scalar_one_or_none()
            if draft_id is None:
                continue
            _assert_no_judgment_rows([row[0] for row in _rows_of(conn, draft_id)], lane=lane, what=f"{lane}/{model} 초안")
            conn.execute(
                sa.insert(prompt_sections_table),
                _section_dicts(judgment, prefix="draft:", lane=lane, model=model, set_id=draft_id),
            )
            patched.append((lane, model))
    return patched


def upgrade() -> None:
    """Upgrade schema."""
    # 배포 중에도 떠 있는 API 가 prompt_sets 를 읽고 쓴다. 이 리비전은 행만 넣어 오래 쥐는 락이 없지만, 다른 트랜잭션 뒤에서
    # 끝없이 기다리지 않고 5초 안에 실패해 배포가 멈추게 첫 문장으로 건다.
    op.execute("SET LOCAL lock_timeout = '5s'")
    bind = op.get_bind()
    seed_published_sets(bind)
    _patch_drafts(bind)


def _delete_draft_rows(conn: Connection) -> None:
    """Claude 체인 초안의 판정·요약 채널 행만 지운다."""
    for lane in _LANES:
        conn.execute(
            sa.text(
                "DELETE FROM prompt_sections s USING prompt_sets p"
                " WHERE p.id = s.prompt_set_id AND p.status = 'draft' AND p.lane = :lane AND p.model IN :models"
                " AND s.channel IN :channels"
            ).bindparams(sa.bindparam("models", expanding=True), sa.bindparam("channels", expanding=True)),
            {"lane": lane, "models": list(_CLAUDE_MODELS), "channels": list(JUDGMENT_CHANNELS[lane])},
        )


def delete_seeded_rows(conn: Connection) -> None:
    """위 docstring 의 `downgrade()`. `op` 를 쓰지 않는 이유는 `seed_published_sets` 와 같다."""
    later: list[str] = []
    for lane in _LANES:
        for model in _CLAUDE_MODELS:
            count = conn.execute(
                sa.text(
                    "SELECT count(*) FROM prompt_sets WHERE status = 'published' AND lane = :lane AND model = :model"
                    " AND id <> :seed AND published_at > (SELECT published_at FROM prompt_sets WHERE id = :seed)"
                ),
                {"lane": lane, "model": model, "seed": NEW_SET_IDS[(lane, model)]},
            ).scalar_one()
            if count:
                later.append(f"{lane}/{model} {count}개")
    if later:
        raise RuntimeError(
            f"시드 뒤에 어드민이 Claude 체인에 게시한 세트가 있다({', '.join(later)}) — 되돌리면 판정·요약 행이 든 그 세트가 활성으로"
            " 남아 이전 코드의 그 체인 게시가 막힌다. 아무것도 지우지 않았다"
        )

    claude_seed_ids = [NEW_SET_IDS[(lane, model)] for lane in _LANES for model in _CLAUDE_MODELS]
    conn.execute(sa.delete(prompt_sections_table).where(prompt_sections_table.c.prompt_set_id.in_(claude_seed_ids)))
    conn.execute(sa.delete(prompt_sets_table).where(prompt_sets_table.c.id.in_(claude_seed_ids)))
    conn.execute(
        sa.text(
            "DELETE FROM prompt_sections WHERE prompt_set_id IN (SELECT id FROM prompt_sets WHERE model = :model)"
        ),
        {"model": _JUDGMENT_ONLY_MODEL},
    )
    conn.execute(sa.text("DELETE FROM prompt_sets WHERE model = :model"), {"model": _JUDGMENT_ONLY_MODEL})
    _delete_draft_rows(conn)


def downgrade() -> None:
    """Downgrade schema."""
    delete_seeded_rows(op.get_bind())
