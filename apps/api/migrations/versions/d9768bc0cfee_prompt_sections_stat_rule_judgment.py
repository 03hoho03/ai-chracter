"""prompt sections stat rule judgment

Revision ID: d9768bc0cfee
Revises: 53149f0bdbcc
Create Date: 2026-10-08 19:00:00.000000

스탯 규칙 판정 채널 `stat_rule_judgment` 의 4행(`stat_defs_intro`·`user_name`·`turn_context`·`judgment_instruction`)을
story 레인 Gemini 체인에 넣는다. 시작설정의 판정 스탯 전부에 작가가 「조건 → ±n」 규칙을 달았으면 판정 LLM 이 절대값 대신
이번 턴에 발동한 규칙의 짧은 id 만 고르고, 폭은 코드가 더한다. 슬롯 구성은 현행 `stat_judgment` 와 같고, 문안은 그 채널의
시드 문안에서 현재값 언급을 뺀 것이다. 현행 채널은 그대로 둔다 — 규칙이 없는 시작설정은 계속 그 채널로 판정한다.

**기존 published 세트는 건드리지 않는다.** story 레인 **`model='gemini'`** 의 활성 세트를 바이트 그대로 복사한 **새
published 세트**를 만들고 4행을 더한다. 다른 행은 body·conditional·order 까지 원본과 같아 이 채널 밖의 렌더는 이 리비전
전과 같다. 활성 SELECT 에 모델 필터를 거는 이유는 레인만 보면 Claude 세트를 원본으로 집을 수 있어서다.

**Claude 체인(sonnet·opus 세트)에는 넣지 않는다.** 그 체인은 생성만 읽고 판정은 늘 Gemini 세트로 하며, 어드민 게시 검증의
그 체인 기대 집합이 system·generation 뿐이라 넣으면 그 체인 게시가 "잉여"로 막힌다.

**가정이 어긋나면 배포를 멈춘다**(`_assert_layout`): story/gemini 세트(활성·초안 각자)에 이 채널 행이 이미 있으면
`RuntimeError`. 체인이 한 트랜잭션이라 앞 리비전도 함께 롤백된다.

**`published_at` 은 SQL `now()` 가 아니라 파이썬 `max(now, 원본 + 1초)` 다** — 체인이 한 트랜잭션이라 SQL `now()` 는 체인
시작 시각이어서, 원본이 같은 체인에서 만들어진 DB(테스트 DB)에서는 새 세트가 원본보다 과거가 될 수 있다. 삽입 뒤 활성
SELECT 를 다시 돌려 새 세트가 뽑히는지 확인한다. `version` 은 전 레인·전 모델 published 최대 + 1 이다(어드민 게시와 같은 규칙).

**초안**: story/gemini 초안이 있으면 초안에도 같은 4행을 제자리에서 넣는다(`_patch_draft`). 다른 행은 건드리지 않는다.

**PK**: 새 세트는 리터럴 UUID(`NEW_SET_ID`). 섹션은 `uuid5(_SECTION_ID_NAMESPACE, "story:{channel}:{scope}:{slot}:{variant}")`,
초안 행은 `draft:` 접두사를 붙인다(`uuid4()` 호출 금지 규약).

**옛 이미지가 이 데이터 위에서 도는 구간**(배포 중 겹침, 이미지만 되돌린 동안) — 옛 코드는 이 채널을 렌더하지 않으므로 새
행은 쓰이지 않고 판정은 현행 그대로다. 다만 옛 코드의 어드민 게시 검증이 새 세트·초안의 이 채널을 "잉여"로 거부해 **story
레인 어드민 게시만** 막힌다 — 그 상태에서 게시가 필요하면 이 리비전 이전 버전을 복원해서 게시한다.

⚠️ **운영 메모**:
- 마이그레이션은 활성 세트 캐시를 지우지 않는다 — 배포 직후 최대 300초 동안 story 레인은 이 채널이 없는 옛 세트로
  렌더한다. 그때 규칙 판정 렌더는 빈 문자열이고, 판정 조립(`prepare_stat_judgment`)이 그것을 보고 현행 판정으로 돌아간다.
- 배포 전부터 열어 둔 어드민 프롬프트 편집 탭에서 저장하면 초안이 섹션 전체 교체로 새 행을 잃고 게시가 슬롯 집합 검사
  ("누락")로 막힌다. **배포 뒤에는 편집 탭을 새로고침한다.**
- **이 리비전 이전 story 버전은 복원해도 게시할 수 없다**(슬롯 집합 검사 "누락", 제약으로 받아들임).

`downgrade()`: 리터럴 세트의 섹션 → 세트 순으로 지우고, story/gemini 초안의 이 채널 행을 지운다(PK 가 아니라 레인·모델·채널로
찾는다 — 초안 저장이 섹션을 통째로 교체해 PK 가 바뀌어 있을 수 있다). 채널 전체가 빠지므로 다른 행의 order 를 당길 필요가
없다. 그 사이 운영자가 게시한 새 버전(이 채널 포함)은 남는다 — 그 세트가 활성이면 이 리비전 이전 코드의 게시 검증이 그 레인
게시를 "잉여"로 막는다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 테스트(`tests/test_stat_rule_judgment_prompt_migration.py`)가 이 모듈을
`importlib` 로 불러 순수 함수와 `seed_published_set`·`_patch_draft`·`delete_seeded_rows` 를 직접 부른다.
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd9768bc0cfee'
down_revision: str | Sequence[str] | None = '53149f0bdbcc'
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

# 리터럴 UUID — 작성 시점에 uuid.uuid4()를 한 번씩 실행해 뽑았다.
NEW_SET_ID = uuid.UUID('2cfa4bc9-ed34-474f-88b9-725c1474a931')
_SECTION_ID_NAMESPACE = uuid.UUID('f7af1a9c-0034-4944-b500-c693a6945fdb')

_LANE = "story"
_MODEL = "gemini"
_CHANNEL = "stat_rule_judgment"

# 적용된 뒤에는 DB에 영구히 남는 값이라 문서명·번호를 넣지 않는다.
_NOTE = "스탯 규칙 판정 채널 추가"

# ---- 문안 ----------------------------------------------------------------------------------
# 스탯 블록(`{stat_lines}`)은 코드(`build_stat_rule_judgment_prompt`)가 만든다 — 스탯마다 `이름 / 범위 / 설명` 한 줄과
# `- 규칙 id: 조건` 줄들. 지시문이 부르는 키 이름은 응답 스키마(`StatRuleJudgmentResult`)의 실제 키(`fired_rule_ids`)와
# 같아야 한다 — 구조화 출력은 필드 이름을 그대로 키로 쓴다.
STAT_DEFS_INTRO_BODY = (
    "다음은 스토리 챗의 스탯 정의와 스탯마다 정해 둔 규칙이다. 규칙 줄은 '- 규칙 id: 조건' 꼴이다.\n"
    "{stat_lines}"
)
USER_NAME_BODY = "대화 속 사용자의 이름: {user_name}"
TURN_CONTEXT_BODY = "[대화 기록]\n{user_label}: {user_message}\n{assistant_label}: {assistant_message}"
JUDGMENT_INSTRUCTION_BODY = (
    "위 대화, 특히 마지막 사용자 행동과 그에 대한 응답에서 이번 턴에 실제로 일어난 일에 해당하는 규칙의 id만 골라 "
    "fired_rule_ids에 담아라. 이미 지난 일을 다시 말하거나 앞으로 할 일을 말한 것은 이번 턴에 일어난 일이 아니다. "
    "규칙의 조건이 그 스탯 설명이 가리키는 인물에게 일어난 일인지 확인하라. 해당하는 규칙이 없으면 빈 목록으로 응답하라."
)

# `(channel, scope, slot, variant, body, conditional, order)` — 새 채널은 기준 행이 없어 order 가 고정이다. 이름 한 줄은
# 현행 스탯 판정처럼 대화 기록 바로 앞에 두고, 이름이 없으면 섹션째 빠진다(conditional).
NEW_ROWS: tuple[tuple[str, str, str, str, str, bool, int], ...] = (
    (_CHANNEL, "story", "stat_defs_intro", "", STAT_DEFS_INTRO_BODY, False, 1),
    (_CHANNEL, "story", "user_name", "", USER_NAME_BODY, True, 2),
    (_CHANNEL, "story", "turn_context", "", TURN_CONTEXT_BODY, False, 3),
    (_CHANNEL, "story", "judgment_instruction", "", JUDGMENT_INSTRUCTION_BODY, False, 4),
)

# `load_active_prompt_set`(chat/prompt_builder.py)과 같은 규칙이다.
_ACTIVE_SET_SQL = sa.text(
    "SELECT id, user_label, story_assistant_label, story_example_label, character_assistant_label,"
    " published_at"
    " FROM prompt_sets WHERE status = 'published' AND lane = :lane AND model = :model"
    " ORDER BY published_at DESC LIMIT 1"
)
_SECTIONS_SQL = sa.text(
    'SELECT channel, scope, slot, variant, body, conditional, "order"'
    " FROM prompt_sections WHERE prompt_set_id = :id"
)


def _assert_layout(channels: Sequence[str]) -> None:
    """`channels` 는 story/gemini 세트 한 벌의 행 channel 목록이다. 이 채널 행이 이미 있으면 두 번 적용되는 것이라
    `RuntimeError`(배포를 멈춘다)."""
    existing = sum(1 for channel in channels if channel == _CHANNEL)
    if existing:
        raise RuntimeError(f"[{_LANE}/{_MODEL}] {_CHANNEL} channel 행이 이미 {existing}개 있다")


def _section_id(prefix: str, channel: str, scope: str, slot: str, variant: str) -> uuid.UUID:
    return uuid.uuid5(_SECTION_ID_NAMESPACE, f"{prefix}{_LANE}:{channel}:{scope}:{slot}:{variant}")


def _build_published_rows(
    source_rows: Sequence[tuple[str, str, str, str, str, bool, int]], set_id: uuid.UUID
) -> list[dict[str, object]]:
    """원본 섹션 전부를 바이트 그대로 새 세트로 복사한 행 목록 + 새 채널 4행.

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
    """story/gemini 초안이 없으면 `False`. 있으면 초안 **자신의** 행으로 가정을 검사한 뒤 새 4행을 제자리에서 넣고
    `True`. 초안은 (레인, 모델)당 1개라(`ix_prompt_sets_draft`) 새 세트를 만들지 않는다.

    `op` 를 쓰지 않는다 — 테스트가 롤백되는 세션의 커넥션에 `run_sync` 로 부르기 위해서다."""
    draft_id = conn.execute(
        sa.text("SELECT id FROM prompt_sets WHERE status = 'draft' AND lane = :lane AND model = :model"),
        {"lane": _LANE, "model": _MODEL},
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
    """story/gemini 초안의 이 채널 행만 지운다."""
    conn.execute(
        sa.text(
            "DELETE FROM prompt_sections s USING prompt_sets p"
            " WHERE p.id = s.prompt_set_id AND p.status = 'draft' AND p.lane = :lane AND p.model = :model"
            " AND s.channel = :channel"
        ),
        {"lane": _LANE, "model": _MODEL, "channel": _CHANNEL},
    )


def seed_published_set(conn: Connection, now: datetime) -> None:
    """활성 story/gemini 세트를 복사한 새 세트에 4행을 더해 넣고, 활성으로 뽑히는지 확인한다. `op` 를 쓰지 않는 이유는
    `_patch_draft` 와 같다."""
    source = conn.execute(_ACTIVE_SET_SQL, {"lane": _LANE, "model": _MODEL}).one()
    rows = conn.execute(_SECTIONS_SQL, {"id": source.id}).fetchall()
    _assert_layout([row.channel for row in rows])

    # `_next_published_version`(admin/prompts.py)과 같은 규칙 — 전 레인·전 모델 대상.
    latest_version = conn.execute(
        sa.text("SELECT max(CAST(version AS INTEGER)) FROM prompt_sets WHERE status = 'published'")
    ).scalar_one()
    conn.execute(
        sa.insert(prompt_sets_table),
        [
            {
                "id": NEW_SET_ID,
                "version": str((latest_version or 0) + 1),
                "status": "published",
                "lane": _LANE,
                "model": _MODEL,
                "user_label": source.user_label,
                "story_assistant_label": source.story_assistant_label,
                "story_example_label": source.story_example_label,
                "character_assistant_label": source.character_assistant_label,
                "note": _NOTE,
                # SQL now()가 아니다 — 위 docstring.
                "published_at": max(now, source.published_at + timedelta(seconds=1)),
            }
        ],
    )
    conn.execute(sa.insert(prompt_sections_table), _build_published_rows([tuple(row) for row in rows], NEW_SET_ID))

    chosen = conn.execute(_ACTIVE_SET_SQL, {"lane": _LANE, "model": _MODEL}).one().id
    if chosen != NEW_SET_ID:
        raise RuntimeError(f"[{_LANE}/{_MODEL}] 새 세트가 활성으로 뽑히지 않는다: 활성={chosen}, 새 세트={NEW_SET_ID}")


def upgrade() -> None:
    """Upgrade schema."""
    # 배포 중에도 떠 있는 API 가 prompt_sets 를 읽고 쓴다. 이 리비전은 행만 넣어 오래 쥐는 락이 없지만, 이 리비전만
    # 올라갈 때(앞 리비전의 `SET LOCAL` 을 물려받지 않는다)에도 다른 트랜잭션 뒤에서 끝없이 기다리지 않고 5초 안에 실패해
    # 배포가 멈추게 첫 문장으로 건다.
    op.execute("SET LOCAL lock_timeout = '5s'")
    bind = op.get_bind()
    seed_published_set(bind, datetime.now(UTC))
    _patch_draft(bind)


def delete_seeded_rows(conn: Connection) -> None:
    """리터럴 세트의 섹션 → 세트 순으로 지우고, story/gemini 초안의 이 채널 행을 지운다. `op` 를 쓰지 않는 이유는
    `_patch_draft` 와 같다."""
    conn.execute(sa.delete(prompt_sections_table).where(prompt_sections_table.c.prompt_set_id == NEW_SET_ID))
    conn.execute(sa.delete(prompt_sets_table).where(prompt_sets_table.c.id == NEW_SET_ID))
    _delete_draft_rows(conn)


def downgrade() -> None:
    """Downgrade schema."""
    delete_seeded_rows(op.get_bind())
