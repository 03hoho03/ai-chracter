"""prompt sections memory episode channel

Revision ID: fc6f0e134782
Revises: f028a5a3b9e6
Create Date: 2026-10-11 22:20:43.408883

장면 기억(접힌 대화 구간에서 뽑은 장면 카드)의 문안 자리를 채팅 두 레인의 체인에 넣는다. 이 리비전만으로는 어떤 호출도 새 행을
읽지 않는다 — 추출 호출과 회상 값은 아직 없어서 새 채널은 렌더되지 않고, 새 생성 슬롯은 값이 비어 섹션째 빠진다.

**심는 것**: story·character 레인마다 네 체인(gemini·sonnet·opus·haiku)에 새 published 세트 하나씩, 모두 여덟.
- 새 채널 `memory_episode`(추출 호출이 렌더하는 문안): 지시문 `instruction`(order 0), 이야기 속 사용자 이름 `user_name`(1,
  conditional), 앞 구간의 마지막 장면 제목 `previous_titles`(2, conditional), 접힌 대화 줄 `turn_context`(3). scope 는 `both`,
  네 체인 모두에 넣는다 — 추출 모델 설정이 어느 체인을 고르든 그 세트에 문안이 있어야 한다.
- 생성 슬롯 `memory_recall`(scope `both`, conditional): 회상한 장면 줄을 싣는 자리. 글을 쓰는 세 체인(gemini·sonnet·opus)의
  `generation` 채널에 `history` **바로 뒤**로 넣는다 — 대화 기록 뒤 섹션은 Claude 프롬프트 캐시의 마지막 블록이라, 턴마다 바뀌는
  회상이 앞 두 블록의 캐시를 깨지 않는다. 판정 전용 체인(haiku)에는 생성 채널이 없어 넣지 않는다.

**새 세트는 그 체인 활성 세트의 바이트 사본에 행을 더한 것이다** — 라벨·모든 기존 행(운영자가 어드민에서 고친 문안, 얼려 둔
소설 행 포함)이 그대로 옮겨진다. 시드 상수가 아니라 활성 세트를 복사하는 이유는 운영 문안이 시드와 다르기 때문이다(시드 문안으로
새 세트를 만들면 운영자가 고친 문안이 조용히 되돌아간다). **게시된 세트는 고치지 않는다** — 기존 세트에 행을 끼워 넣지 않는다.

**위치는 기준 행의 현재 order 다.** 운영자가 어드민에서 order 를 맞바꿀 수 있어서다. `generation` 의 `history` order 를 `H` 로
읽어 그 채널의 `order > H` 를 +1 하고 새 행을 `H+1` 에 둔다(스토리는 키워드북 앞, 캐릭터는 마지막 프레임 앞이 된다). 나머지
행의 상대 순서는 그대로다.

**`published_at` — 두 활성 조회 규칙을 함께 만족시킨다.**
- 레인만 보는 조회(모델 열을 모르는 원시 SQL)는 레인의 최신 게시본을 고른다 — 새 Gemini 세트가 그 레인에서 가장 나중이어야 계속
  Gemini 세트를 집는다. 그래서 새 Gemini 세트는 파이썬 `max(now, 원본 + 1초)` 다(SQL `now()` 는 체인 시작 시각이라, 원본이 같은
  체인에서 만들어진 테스트 DB 에서는 원본보다 과거가 될 수 있다).
- 모델로 거르는 조회(`load_active_prompt_set`)는 (레인, 모델)마다 최신 게시본을 고른다 — 다른 세 체인의 새 세트는 그 체인 활성
  세트보다 나중이고 새 Gemini 세트보다 과거여야 한다. 그래서 (그 체인 활성 시각, 그 레인 새 Gemini 세트 시각)의 **중간값**이다.
  사이에 둘 시각이 없으면 `RuntimeError`.
- 시각은 이 리비전이 도는 순간 DB 에서 다시 읽어 계산한다. 삽입 뒤 두 규칙으로 다시 SELECT 해 확인한다: 여덟 체인 활성이 새 세트,
  레인만 보는 활성이 새 Gemini 세트. 어긋나면 `RuntimeError`.

**가정이 어긋나면 배포를 멈춘다**(`RuntimeError`, 체인이 한 트랜잭션이라 앞 리비전까지 함께 롤백된다): 레인만 보는 조회가 이미
Gemini 가 아닌 세트를 집을 때, 어느 세트(활성·초안)에 `memory_episode` 행이 이미 있을 때, 글을 쓰는 체인의 세트에 `generation`
의 `history` 행이 정확히 하나가 아니거나 `memory_recall` 행이 이미 있을 때.

**초안**: 여덟 체인 중 초안이 있는 체인은 초안 **자신의** 행으로 같은 가정을 검사한 뒤 같은 행을 제자리에서 넣고 order 를 민다
(`_patch_drafts`). 기존 행의 body 는 건드리지 않는다.

**PK**: 세트는 리터럴 UUID(`NEW_SET_IDS`), 섹션은 새 namespace 의 `uuid5("{lane}:{model}:{channel}:{scope}:{slot}:{variant}")`
(초안 행은 `draft:` 접두). 복사한 기존 행도 같은 규칙으로 새 id 를 받는다. `version` 은 전 레인·전 모델 published 최대 + 1 을
(story, character) × (gemini, sonnet, opus, haiku) 순서로 매긴다(어드민 게시와 같은 규칙).

**문안**은 이 파일의 `*_BODY` 상수가 유일한 소스다. 추출 지시문은 오프라인 평가에서 확정한 판을 바이트 그대로 옮겼다.

**옛 이미지가 이 데이터 위에서 도는 구간**(배포 중 겹침, 이미지만 되돌린 동안): 옛 코드는 회상 값을 넘기지 않아 새 생성 슬롯이
섹션째 빠지고(생성 글이 바이트까지 같다), `memory_episode` 채널은 읽는 코드가 없다. 옛 코드의 어드민 게시 검증은 새 세트·초안의
새 행을 "잉여"로 거부해 **여덟 체인의 어드민 게시만** 막힌다.

⚠️ **운영 메모**:
- 마이그레이션은 활성 세트 캐시를 지우지 않는다 — 배포 직후 최대 300초 동안 옛 세트로 렌더할 수 있다. 새 행이 없을 뿐 생성 글은
  같다.
- 배포 전부터 열어 둔 어드민 프롬프트 편집 탭에서 저장하면 초안이 섹션 전체 교체로 새 행을 잃고 게시가 "누락"으로 막힌다.
  **배포 뒤에는 편집 탭을 새로고침한다.**
- 회상 슬롯 body 에서 `{memory_recall_lines}` 를 지우면 드롭 조건이 거짓이 되어 **모든 턴에 머리글만 나간다**. 게시 검증은 "허용
  밖 이름"만 막고 "필수 이름의 존재"는 보지 않는다.
- 🔴 **시드를 손으로 지우지 않는다.** 지우면 다시 배포할 때 `alembic upgrade head` 가 이미 적용된 이 리비전을 건너뛰어, 체인들이
  새 행 없는 이전 세트로 돌아가고 새 코드의 게시가 "누락"으로 막힌다. 되돌리려면 아래 `downgrade` 를 쓴다.
- 🔴 **프롬프트 옛 버전을 통째로 복원하지 않는다.** 이 리비전 이전 버전은 새 행이 없어 새 코드에서 게시가 막히고, 옛 이미지에서
  복원·게시하면 새 행이 사라진다 — 현재 활성본에서 바뀐 섹션만 고친다.

**롤백 순서**: ① 1순위는 이미지만 되돌리기(위 겹침 구간과 같은 상태 — 막히는 것은 여덟 체인의 어드민 게시뿐) → ② `downgrade` 가
필요하면 **새 이미지로** 실행한 뒤 이미지를 되돌린다.

`downgrade()`(`delete_seeded_rows`): 시드 뒤에 어드민이 여덟 체인 중 하나에 새 버전을 게시했으면 아무것도 지우지 않고
`RuntimeError` 로 멈춘다 — 그 게시본에도 새 행이 있어 되돌린 뒤 활성으로 남으면 이전 코드의 게시 검증이 그 체인을 막고, 푸는 길이
옛 버전 통째 복원뿐이라 사람이 판단해야 한다. 없으면 리터럴 시드의 섹션 → 세트를 지우고, 초안의 새 행을 지우며 그 뒤 행의
order 를 −1 한다(PK 가 아니라 레인·모델·채널·슬롯으로 찾는다 — 초안 저장이 섹션을 통째로 교체해 PK 가 바뀌어 있을 수 있다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 테스트(`tests/test_memory_episode_prompt_migration.py`)가 이 모듈을
`importlib` 로 불러 순수 함수와 `seed_published_sets`·`_patch_drafts`·`delete_seeded_rows` 를 직접 부른다.
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'fc6f0e134782'
down_revision: str | Sequence[str] | None = 'f028a5a3b9e6'
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
# 글을 쓰는 체인 — 생성 채널이 있어 회상 슬롯을 받는다. Gemini 가 맨 앞이어야 한다(다른 체인의 게시 시각이 새 Gemini 세트 시각에
# 기댄다).
_WRITING_MODELS: tuple[str, ...] = (_GEMINI, "sonnet", "opus")
_JUDGMENT_ONLY_MODEL = "haiku"
_MODELS: tuple[str, ...] = (*_WRITING_MODELS, _JUDGMENT_ONLY_MODEL)

# 리터럴 UUID — 작성 시점에 uuid.uuid4()를 한 번씩 실행해 뽑았다.
NEW_SET_IDS: dict[tuple[str, str], uuid.UUID] = {
    ("story", "gemini"): uuid.UUID('7aa4122b-a9db-4003-bbe0-ee130b46034b'),
    ("story", "sonnet"): uuid.UUID('99c2b0f5-3c36-4a96-adbd-d226e430b4f8'),
    ("story", "opus"): uuid.UUID('3db7a362-b2a1-4927-82d1-f6aeb4c94e3c'),
    ("story", "haiku"): uuid.UUID('2517d852-c29f-4271-83c0-b5799da1ade0'),
    ("character", "gemini"): uuid.UUID('a80dffe5-207a-4a95-abac-95cda93d9219'),
    ("character", "sonnet"): uuid.UUID('9c029822-2229-48c6-bd0e-03312c2b618b'),
    ("character", "opus"): uuid.UUID('952ae5d4-5fa9-4cba-b6ba-d5970ac119ab'),
    ("character", "haiku"): uuid.UUID('1b13a6d3-2747-4348-8e63-10aafceeb1ce'),
}
_SECTION_ID_NAMESPACE = uuid.UUID('bd2bc7bb-a370-4591-8fa7-52ef444348bf')

# 적용된 뒤에는 DB에 영구히 남는 값이라 문서명·번호를 넣지 않는다.
_NOTE_WRITING = "장면 기억 추출 문안 채널과 회상 슬롯 추가(활성 세트 사본)"
_NOTE_JUDGMENT_ONLY = "장면 기억 추출 문안 채널 추가(활성 세트 사본)"

# ---- 문안 ----------------------------------------------------------------------------------
EPISODE_CHANNEL = "memory_episode"
RECALL_SLOT = "memory_recall"
_GENERATION = "generation"
_HISTORY_SLOT = "history"

# 추출 지시문 — 오프라인 평가(개발 절반)에서 확정한 판을 바이트 그대로 옮겼다. 줄바꿈과 들여쓰기까지 그 판과 같다.
EPISODE_INSTRUCTION_BODY = (
    "너는 롤플레이 대화의 기억을 정리하는 기록자다. 아래 [접힌 대화]는 이야기에서 지나간 한 구간이다. 이 구간을 장면 단위로\n"
    "나눠, 나중에 \"그때 그거 기억나?\"라는 물음에 답할 수 있게 기억 카드로 남긴다.\n"
    "\n"
    "1. 장면은 많아야 10개다 — 11번째부터는 버려져 그 줄들의 기억이 사라진다. 그래서 먼저 [접힌 대화]의 마지막 줄 번호를 보고,\n"
    "   1번 줄부터 마지막 줄까지를 10개 이하의 장면으로 빠짐없이 나눈다. 모든 줄이 어느 한 장면에 들어가고, 마지막 줄까지 가기\n"
    "   전에 멈추지 않는다. 장면은 장소·시간·함께 있는 인물·하는 일이 바뀌는 곳에서 나누되, 주고받은 말 한 번마다 장면을 따로\n"
    "   만들지 않는다 — 장면 하나가 보통 여러 번의 주고받음을 덮는다. 바뀌는 곳이 10개보다 많으면 이웃한 장면을 합친다.\n"
    "2. detail 에는 나중에 다시 물을 만한 구체적인 것을 원문 낱말 그대로 남긴다 — 가게·장소 이름, 먹고 마신 것, 주고받은 물건,\n"
    "   날짜·요일·시각, 약속, 털어놓은 사정, 인물이 한 구체적인 말. \"맛있는 것을 먹었다\"처럼 뭉개지 말고 무엇을 먹었는지 쓴다.\n"
    "   장면이 여러 줄에 걸치면 앞쪽 줄뿐 아니라 뒤쪽 줄의 구체적인 것도 고루 남긴다. 300자를 넘기지 않는다.\n"
    "3. 대화에 없는 것을 보태지 않는다. 짐작·해석·감정 평가를 쓰지 않는다.\n"
    "4. asserted_by 는 그 장면의 핵심 사실을 누가 말했는가다. 사용자 줄에서 나온 사실은 user, 인물이 대사로 말한 것은 character,\n"
    "   진행자의 서술은 narration, 섞였으면 mixed. 인물이 사용자에 대해 \"너 예전에 …했잖아\"라고 한 말은 사용자가 확인한 사실이\n"
    "   아니므로 character 다.\n"
    "5. nouns 는 detail 속 고유명사·구체 명사를 원문 표기 그대로, 조사를 떼고 적는다. keywords 는 이 장면을 다시 찾을 때 쓸 만한\n"
    "   낱말(무엇을 했는가) 몇 개다.\n"
    "6. evidence 는 핵심 사실이 드러난 원문을 한두 줄, 짧게 그대로 옮긴다(줄 번호는 빼고).\n"
    "7. importance 는 이 장면이 나중에 다시 나올 가능성이다 — 1(사소한 일상) ~ 5(관계·약속·비밀처럼 오래 남을 일).\n"
    "8. start_line·end_line 은 그 장면이 시작하고 끝나는 [접힌 대화]의 줄 번호다. 첫 장면은 1에서 시작하고, 마지막 장면은\n"
    "   [접힌 대화]의 마지막 줄 번호에서 끝난다.\n"
    "9. [앞 구간의 마지막 장면]은 제목을 맞추는 데만 쓴다. 이 구간의 첫 장면이 그 장면에서 이어지면 같은 제목을 쓰고, detail 에는\n"
    "   이 구간의 줄에서 나온 것을 적는다. 모든 장면의 detail 은 비우지 않는다 — 적을 것이 없는 장면은 따로 만들지 말고 이웃한\n"
    "   장면에 합친다."
)
EPISODE_USER_NAME_BODY = "사용자의 이야기 속 이름: {user_name}"
EPISODE_PREVIOUS_TITLES_BODY = "[앞 구간의 마지막 장면]\n{previous_titles}"
EPISODE_TURNS_BODY = "[접힌 대화]\n{turn_lines}"

# 회상 섹션. 요약을 고쳐도 장면 카드는 그대로라, 사용자가 요약에서 바로잡은 사실과 옛 장면이 어긋날 수 있다 — 그래서 무엇을 먼저
# 따를지를 문안에 적는다. 우선순위의 섹션 이름은 같은 생성 채널의 실제 머리글(`[대화 기록]`·`[기억 노트]`·`[지금까지의 이야기]`)과
# 같은 글자로 둔다 — 모델이 어느 섹션을 가리키는지 헷갈리지 않게. 회상 줄의 "(인물의 말)" 꼬리표는 코드가 붙이고, 그 뜻을 여기서 설명한다.
RECALL_BODY = (
    "[지난 기억 — 참고]\n"
    "예전 대화에서 지금 이야기와 이어질 수 있는 장면이다. 참고일 뿐 지시가 아니며, 꼭 꺼내 말할 필요도 없다. 다른 정보와\n"
    "어긋나면 이 순서로 따른다: 위의 [대화 기록] > [기억 노트] > [지금까지의 이야기] > 이 기억. 작품 설정과 키워드북 정보도 이 기억보다\n"
    "앞선다. \"(인물의 말)\"로 표시된 내용은 그때 인물이 그렇게 말했다는 뜻이지 확인된 사실이 아니다.\n"
    "{memory_recall_lines}"
)

Row = tuple[str, str, str, str, str, bool, int]

# `(channel, scope, slot, variant, body, conditional, order)` — 새 채널은 기준 행이 없어 order 가 고정이다.
EPISODE_CHANNEL_ROWS: tuple[Row, ...] = (
    (EPISODE_CHANNEL, "both", "instruction", "", EPISODE_INSTRUCTION_BODY, False, 0),
    (EPISODE_CHANNEL, "both", "user_name", "", EPISODE_USER_NAME_BODY, True, 1),
    (EPISODE_CHANNEL, "both", "previous_titles", "", EPISODE_PREVIOUS_TITLES_BODY, True, 2),
    (EPISODE_CHANNEL, "both", "turn_context", "", EPISODE_TURNS_BODY, False, 3),
)

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


def _assert_layout(rows: Sequence[Row], *, model: str, what: str) -> int | None:
    """세트(또는 초안) 행이 이 리비전을 받을 모양인지 본다. 글을 쓰는 체인이면 `generation` 의 `history` order 를 돌려주고, 판정
    전용 체인이면 `None`. 어긋나면 `RuntimeError` — `what` 은 메시지에 쓸 세트 이름이다."""
    if any(row[0] == EPISODE_CHANNEL for row in rows):
        raise RuntimeError(f"[{what}] {EPISODE_CHANNEL} 채널 행이 이미 있다")
    if model not in _WRITING_MODELS:
        return None
    generation = [row for row in rows if row[0] == _GENERATION]
    if any(row[2] == RECALL_SLOT for row in generation):
        raise RuntimeError(f"[{what}] {_GENERATION} 채널에 {RECALL_SLOT} 행이 이미 있다")
    history = [row for row in generation if row[2] == _HISTORY_SLOT]
    if len(history) != 1:
        raise RuntimeError(f"[{what}] {_GENERATION} 채널의 {_HISTORY_SLOT} 행이 정확히 하나가 아니다({len(history)}개)")
    return history[0][6]


def _with_new_rows(rows: Sequence[Row], history_order: int | None) -> list[Row]:
    """기존 행 + 이 리비전의 행. `history_order` 가 있으면(글을 쓰는 체인) 생성 채널에서 그 뒤 행을 하나씩 밀고 회상 슬롯을 바로
    뒤에 둔다. 기존 행의 다른 값은 그대로다."""
    result: list[Row] = []
    for channel, scope, slot, variant, body, conditional, order in rows:
        if history_order is not None and channel == _GENERATION and order > history_order:
            order += 1
        result.append((channel, scope, slot, variant, body, conditional, order))
    if history_order is not None:
        result.append((_GENERATION, "both", RECALL_SLOT, "", RECALL_BODY, True, history_order + 1))
    result.extend(EPISODE_CHANNEL_ROWS)
    return result


def _gemini_seed_time(gemini_at: datetime, now: datetime) -> datetime:
    """새 Gemini 세트의 게시 시각 — 레인에서 가장 나중이 되게 `max(now, 원본 + 1초)`."""
    return max(now, gemini_at + timedelta(seconds=1))


def _seed_time(chain_at: datetime, gemini_seed_at: datetime) -> datetime:
    """Gemini 가 아닌 체인의 새 세트 게시 시각 — 그 체인 활성 시각과 그 레인 새 Gemini 세트 시각의 중간값(위 docstring). 사이에
    둘 시각이 없으면 `RuntimeError`."""
    chosen = chain_at + (gemini_seed_at - chain_at) / 2
    if not chain_at < chosen < gemini_seed_at:
        raise RuntimeError(
            f"두 활성 조회 규칙을 함께 만족하는 게시 시각이 없다: 체인 활성 {chain_at}, 새 Gemini 세트 {gemini_seed_at}"
        )
    return chosen


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
                "note": _NOTE_WRITING if model in _WRITING_MODELS else _NOTE_JUDGMENT_ONLY,
                "published_at": published_at,
            }
        ],
    )
    conn.execute(sa.insert(prompt_sections_table), _section_dicts(rows, prefix="", lane=lane, model=model, set_id=set_id))


def seed_published_sets(conn: Connection) -> None:
    """레인마다 네 체인에 새 세트를 넣고, 두 활성 조회 규칙으로 다시 확인한다.

    `op` 를 쓰지 않는다 — 테스트가 롤백되는 세션의 커넥션에 `run_sync` 로 부르기 위해서다."""
    for lane in _LANES:
        sources = {model: conn.execute(_ACTIVE_SET_SQL, {"lane": lane, "model": model}).one() for model in _MODELS}
        lane_only = conn.execute(_LANE_ONLY_ACTIVE_SET_SQL, {"lane": lane}).one().id
        if lane_only != sources[_GEMINI].id:
            raise RuntimeError(
                f"[{lane}] 레인만 보는 활성 조회가 이미 Gemini 세트가 아닌 {lane_only} 를 집는다 — 두 활성 조회 규칙을 함께"
                " 만족하는 게시 시각이 없다"
            )
        # 넣기 전에 네 체인을 모두 검사한다 — 하나라도 어긋나면 아무것도 넣지 않은 채 멈춘다.
        source_rows = {model: _rows_of(conn, sources[model].id) for model in _MODELS}
        history_orders = {
            model: _assert_layout(source_rows[model], model=model, what=f"{lane}/{model}") for model in _MODELS
        }

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
                rows=_with_new_rows(source_rows[model], history_orders[model]),
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


def _patch_drafts(conn: Connection) -> list[tuple[str, str]]:
    """초안이 있는 체인은 초안 **자신의** 행으로 가정을 검사한 뒤 같은 행을 제자리에서 넣는다(글을 쓰는 체인은 `history` 뒤 행의
    order 를 민다). 손댄 (레인, 모델) 목록을 돌려준다. `op` 를 쓰지 않는 이유는 `seed_published_sets` 와 같다."""
    patched: list[tuple[str, str]] = []
    for lane in _LANES:
        for model in _MODELS:
            draft_id = conn.execute(_DRAFT_SQL, {"lane": lane, "model": model}).scalar_one_or_none()
            if draft_id is None:
                continue
            history_order = _assert_layout(_rows_of(conn, draft_id), model=model, what=f"{lane}/{model} 초안")
            new_rows = list(EPISODE_CHANNEL_ROWS)
            if history_order is not None:
                conn.execute(
                    sa.text(
                        'UPDATE prompt_sections SET "order" = "order" + 1'
                        ' WHERE prompt_set_id = :id AND channel = :channel AND "order" > :history'
                    ),
                    {"id": draft_id, "channel": _GENERATION, "history": history_order},
                )
                new_rows.append((_GENERATION, "both", RECALL_SLOT, "", RECALL_BODY, True, history_order + 1))
            conn.execute(
                sa.insert(prompt_sections_table),
                _section_dicts(new_rows, prefix="draft:", lane=lane, model=model, set_id=draft_id),
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
    """초안의 `memory_episode` 행과 회상 슬롯 행을 지우고, 회상 슬롯 뒤 생성 행의 order 를 −1 한다."""
    draft_ids = sa.text(
        "SELECT id FROM prompt_sets WHERE status = 'draft' AND lane IN :lanes"
    ).bindparams(sa.bindparam("lanes", expanding=True))
    for draft_id in conn.execute(draft_ids, {"lanes": list(_LANES)}).scalars().all():
        conn.execute(
            sa.text("DELETE FROM prompt_sections WHERE prompt_set_id = :id AND channel = :channel"),
            {"id": draft_id, "channel": EPISODE_CHANNEL},
        )
        recall_orders = conn.execute(
            sa.text(
                'DELETE FROM prompt_sections WHERE prompt_set_id = :id AND channel = :channel AND slot = :slot'
                ' RETURNING "order"'
            ),
            {"id": draft_id, "channel": _GENERATION, "slot": RECALL_SLOT},
        ).scalars().all()
        for recall_order in sorted(recall_orders, reverse=True):
            conn.execute(
                sa.text(
                    'UPDATE prompt_sections SET "order" = "order" - 1'
                    ' WHERE prompt_set_id = :id AND channel = :channel AND "order" > :recall'
                ),
                {"id": draft_id, "channel": _GENERATION, "recall": recall_order},
            )


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
            f"시드 뒤에 어드민이 게시한 세트가 있다({', '.join(later)}) — 되돌리면 장면 기억 행이 든 그 세트가 활성으로 남아 이전"
            " 코드의 그 체인 게시가 막힌다. 아무것도 지우지 않았다"
        )

    seed_ids = list(NEW_SET_IDS.values())
    conn.execute(sa.delete(prompt_sections_table).where(prompt_sections_table.c.prompt_set_id.in_(seed_ids)))
    conn.execute(sa.delete(prompt_sets_table).where(prompt_sets_table.c.id.in_(seed_ids)))
    _delete_draft_rows(conn)


def downgrade() -> None:
    """Downgrade schema."""
    delete_seeded_rows(op.get_bind())
