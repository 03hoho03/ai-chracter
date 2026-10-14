"""prompt sections memory fact channel

Revision ID: 5cab2abe4e7b
Revises: 897bf519420f
Create Date: 2026-10-14 18:00:00.000000

관계·사실 기억(접힌 대화 구간에서 뽑은 인물 관계와 사실 행)의 문안 자리를 채팅 두 레인의 체인에 넣고, 장면 기억 추출 지시문과
회상 섹션 문안을 바꾼다. 이 리비전만으로는 어떤 호출도 새 행을 읽지 않는다 — 사실 추출 호출과 사실 값은 아직 없어서 새 채널은
렌더되지 않고, 새 생성 슬롯은 값이 비어 섹션째 빠진다. 바뀌는 두 본문은 바로 효과가 있다: 장면 추출 지시문은 다음 접기부터
새 문안으로 렌더되고, 회상 섹션은 회상이 있는 턴에 새 문안으로 나간다.

**심는 것**: story·character 레인마다 네 체인(gemini·sonnet·opus·haiku)에 새 published 세트 하나씩, 모두 여덟.
- 새 채널 `memory_fact`(추출 호출이 렌더하는 문안): 지시문 `instruction`(order 0), 이야기 속 사용자 이름 `user_name`(1,
  conditional), 앞 구간까지 뽑아 둔 키 목록 `existing_facts`(2), 접힌 대화 줄 `turn_context`(3). scope 는 `both`, 네 체인 모두에
  넣는다 — 추출 모델 설정이 어느 체인을 고르든 그 세트에 문안이 있어야 한다. `existing_facts` 는 conditional 이 아니다 — 첫
  구간에도 머리글과 "(없음)"이 실려야 문안을 다듬을 때 측정한 프롬프트와 바이트까지 같다(값이 없을 때 "(없음)"은 코드가 넘긴다).
- 생성 슬롯 `memory_facts`(scope `both`, conditional): 관계·사실 줄을 싣는 자리. 글을 쓰는 세 체인(gemini·sonnet·opus)의
  `generation` 채널에서 `memory_recall` **바로 앞**에 넣는다 — 대화 기록 뒤 Claude 프롬프트 캐시의 마지막 블록 안이라 턴마다
  바뀌어도 앞 두 블록의 캐시를 깨지 않고, 회상보다 앞서 따를 정보라 회상 앞에 둔다. 판정 전용 체인(haiku)에는 생성 채널이 없다.
- 본문 교체: 장면 추출 `memory_episode`/`instruction`(여덟 체인)은 날짜·시각·숫자를 원문 표기 그대로 남기라는 문장을 더한 판으로,
  회상 `generation`/`memory_recall`(글을 쓰는 여섯 체인)은 "(사용자의 말)" 꼬리표의 뜻과 우선순위에 관계·사실 섹션을 넣은 판으로.

**새 세트는 그 체인 활성 세트의 바이트 사본에 행을 더하고 두 본문만 바꾼 것이다** — 라벨·다른 모든 행(운영자가 어드민에서 고친
문안, 얼려 둔 소설 행 포함)이 그대로 옮겨진다. **게시된 세트는 고치지 않는다.**

**바꾸는 두 본문은 활성 본문이 앞 리비전이 심은 문안(`OLD_*_BODY`)과 바이트로 같을 때만 바꾼다.** 다르면 어드민이 고쳐 게시한
운영 문안이라 조용히 덮어쓰지 않고 `RuntimeError` 로 배포를 멈춘다 — 사람이 고친 문안과 새 문안을 합칠지 판단해야 한다.

**위치는 기준 행의 현재 order 다.** `generation` 의 `memory_recall` order 를 `R` 로 읽어 그 채널의 `order >= R` 를 +1 하고 새 행을
`R` 에 둔다. 나머지 행의 상대 순서는 그대로다.

**`published_at` — 두 활성 조회 규칙을 함께 만족시킨다**(앞 리비전 `fc6f0e134782` 와 같은 규칙).
- 레인만 보는 조회(모델 열을 모르는 원시 SQL)는 레인의 최신 게시본을 고른다 — 새 Gemini 세트는 파이썬 `max(now, 원본 + 1초)`.
- 모델로 거르는 조회(`load_active_prompt_set`)는 (레인, 모델)마다 최신 게시본을 고른다 — 다른 세 체인의 새 세트는 (그 체인 활성
  시각, 그 레인 새 Gemini 세트 시각)의 **중간값**. 사이에 둘 시각이 없으면 `RuntimeError`.
- 삽입 뒤 두 규칙으로 다시 SELECT 해 확인한다. 어긋나면 `RuntimeError`.

**가정이 어긋나면 배포를 멈춘다**(`RuntimeError`, 체인이 한 트랜잭션이라 앞 리비전까지 함께 롤백된다): 레인만 보는 조회가 이미
Gemini 가 아닌 세트를 집을 때, 어느 세트(활성·초안)에 `memory_fact` 행이나 `memory_facts` 행이 이미 있을 때, `memory_episode`
의 `instruction` 행이 정확히 하나가 아닐 때, 글을 쓰는 체인의 세트에 `generation` 의 `memory_recall` 행이 정확히 하나가 아닐 때,
게시본의 바꾸는 두 본문이 앞 리비전 문안과 다를 때.

**초안**: 여덟 체인 중 초안이 있는 체인은 초안 **자신의** 행으로 같은 모양 가정을 검사한 뒤 새 행을 제자리에서 넣고 order 를
민다(`_patch_drafts`). 바꾸는 두 본문은 초안 본문이 앞 리비전 문안과 같을 때만 바꾸고, 다르면 그대로 둔다 — 초안은 운영자가
고치던 중인 문안이라 덮어쓰면 그 작업이 사라지고, 초안 하나 때문에 배포를 멈출 일도 아니다(게시할 때 운영자가 새 문안과 견준다).

**PK**: 세트는 리터럴 UUID(`NEW_SET_IDS`), 섹션은 새 namespace 의 `uuid5("{lane}:{model}:{channel}:{scope}:{slot}:{variant}")`
(초안 행은 `draft:` 접두). `version` 은 전 레인·전 모델 published 최대 + 1 을 (story, character) × (gemini, sonnet, opus, haiku)
순서로 매긴다(어드민 게시와 같은 규칙).

**문안**은 이 파일의 `*_BODY` 상수가 유일한 소스다. 사실 추출 지시문과 장면 추출 새 지시문은 측정에서 다듬은 판을 바이트 그대로
옮겼다.

**옛 이미지가 이 데이터 위에서 도는 구간**(배포 중 겹침, 이미지만 되돌린 동안): 옛 코드는 사실 값을 넘기지 않아 새 생성 슬롯이
섹션째 빠지고, `memory_fact` 채널은 읽는 코드가 없다. 바뀐 두 본문은 옛 코드에서도 같은 플레이스홀더라 그대로 렌더된다. 옛 코드의
어드민 게시 검증은 새 세트·초안의 새 행을 "잉여"로 거부해 **여덟 체인의 어드민 게시만** 막힌다.

⚠️ **운영 메모**:
- 마이그레이션은 활성 세트 캐시를 지우지 않는다 — 배포 직후 최대 300초 동안 옛 세트(옛 두 본문)로 렌더할 수 있다.
- 배포 전부터 열어 둔 어드민 프롬프트 편집 탭에서 저장하면 초안이 섹션 전체 교체로 새 행을 잃고 게시가 "누락"으로 막힌다.
  **배포 뒤에는 편집 탭을 새로고침한다.**
- 사실 슬롯 body 에서 `{memory_fact_lines}` 를 지우면 드롭 조건이 거짓이 되어 **모든 턴에 머리글만 나간다**.
- 🔴 **시드를 손으로 지우지 않는다.** 되돌리려면 아래 `downgrade` 를 쓴다.
- 🔴 **프롬프트 옛 버전을 통째로 복원하지 않는다** — 현재 활성본에서 바뀐 섹션만 고친다.

**롤백 순서**: ① 1순위는 이미지만 되돌리기(막히는 것은 여덟 체인의 어드민 게시뿐이고, 바뀐 두 본문은 남는다) → ② 옛 두 본문까지
되돌려야 하면 **새 이미지로** `downgrade` 를 실행한 뒤 이미지를 되돌린다.

`downgrade()`(`delete_seeded_rows`): 시드 뒤에 어드민이 여덟 체인 중 하나에 새 버전을 게시했으면 아무것도 지우지 않고
`RuntimeError` 로 멈춘다(앞 리비전과 같은 이유). 없으면 리터럴 시드의 섹션 → 세트를 지운다 — 이전 활성 세트는 처음부터 옛 두
본문을 갖고 있다. 초안은 새 행을 지우고 그 뒤 행의 order 를 −1 하며, 두 본문이 이 리비전의 새 문안과 같으면 옛 문안으로
되돌린다(PK 가 아니라 레인·모델·채널·슬롯으로 찾는다 — 초안 저장이 섹션을 통째로 교체해 PK 가 바뀌어 있을 수 있다).

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 테스트(`tests/test_memory_fact_prompt_migration.py`)가 이 모듈을
`importlib` 로 불러 `seed_published_sets`·`_patch_drafts`·`delete_seeded_rows` 를 직접 부른다.
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5cab2abe4e7b'
down_revision: str | Sequence[str] | None = '897bf519420f'
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
# 글을 쓰는 체인 — 생성 채널이 있어 사실 슬롯을 받는다. Gemini 가 맨 앞이어야 한다(다른 체인의 게시 시각이 새 Gemini 세트 시각에
# 기댄다).
_WRITING_MODELS: tuple[str, ...] = (_GEMINI, "sonnet", "opus")
_JUDGMENT_ONLY_MODEL = "haiku"
_MODELS: tuple[str, ...] = (*_WRITING_MODELS, _JUDGMENT_ONLY_MODEL)

# 리터럴 UUID — 작성 시점에 uuid.uuid4()를 한 번씩 실행해 뽑았다.
NEW_SET_IDS: dict[tuple[str, str], uuid.UUID] = {
    ("story", "gemini"): uuid.UUID('d46ec236-1579-4412-a6e6-f117352df6f6'),
    ("story", "sonnet"): uuid.UUID('1259a02b-2a60-4eb8-9910-13b46972ac58'),
    ("story", "opus"): uuid.UUID('9a36afa9-63f9-4424-837b-25d5513ed90e'),
    ("story", "haiku"): uuid.UUID('ee8b2414-66fc-413e-9f78-4c3f4559565a'),
    ("character", "gemini"): uuid.UUID('4cdd116f-af1b-40c3-b26e-8d036696bf46'),
    ("character", "sonnet"): uuid.UUID('368ef074-5593-4f86-9e2d-335db28e0ca3'),
    ("character", "opus"): uuid.UUID('ead8bd84-0df8-4d92-bcc5-3b803cce1278'),
    ("character", "haiku"): uuid.UUID('916fcb88-869f-4155-be8d-377430fdc56b'),
}
_SECTION_ID_NAMESPACE = uuid.UUID('8399ebd0-ac08-43bb-b3f4-1a0bd62fe66f')

# 적용된 뒤에는 DB에 영구히 남는 값이라 문서명·번호를 넣지 않는다.
_NOTE_WRITING = "관계·사실 기억 추출 문안 채널과 사실 슬롯 추가, 장면 추출·회상 문안 교체(활성 세트 사본)"
_NOTE_JUDGMENT_ONLY = "관계·사실 기억 추출 문안 채널 추가, 장면 추출 문안 교체(활성 세트 사본)"

# ---- 문안 ----------------------------------------------------------------------------------
FACT_CHANNEL = "memory_fact"
FACTS_SLOT = "memory_facts"
EPISODE_CHANNEL = "memory_episode"
RECALL_SLOT = "memory_recall"
_INSTRUCTION_SLOT = "instruction"
_GENERATION = "generation"

# 사실 추출 지시문 — 측정에서 다듬은 판을 바이트 그대로 옮겼다(파일 끝 개행 하나만 뗐다 — 렌더가 섹션을 빈 줄로 잇는다).
FACT_INSTRUCTION_BODY = (
    "너는 롤플레이 대화의 기억을 정리하는 기록자다. 아래 [접힌 대화]는 이야기에서 지나간 한 구간이다. 이 구간에서 인물 사이의 관계와\n"
    "나중에도 맞아야 할 사실을 짧은 행으로 뽑아, 이야기가 길어져도 \"누가 누구를 어떻게 대하는가\", \"무엇이 사실이고 무엇이 말뿐인가\"를\n"
    "잊지 않게 한다. [기존 키]는 이 구간 앞까지 뽑아 둔 행을 키마다 가장 최근 값 하나로 줄인 목록이다. 같은 키의 새 행은 옛 행을 덮어쓴다.\n"
    "\n"
    "1. 행은 두 종류다. relation 은 한 인물이 다른 인물을 지금 어떻게 대하는가다 — subject 가 object 를 대하는 태도를 value 에 쓰고\n"
    "   attribute 는 빈 문자열로 둔다. 방향이 있다: A → B 행과 B → A 행은 다른 행이다. fact 는 subject(인물·장소·물건·단체)의\n"
    "   attribute 가 value 라는 것이고 object 는 빈 문자열로 둔다. 한 번 하고 지나간 일(무엇을 먹었다, 어디를 걸었다)은 쓰지 않는다 —\n"
    "   나중에도 맞는 상태·약속·사정·정보만 쓴다. 일정·장소·시각·물건 정보를 relation 의 value 에 끼워 넣지 말고 따로 fact 로 쓴다.\n"
    "2. relation 의 value 는 \"상태 낱말 — 근거\" 꼴로 짧게 쓴다. 상태 낱말은 경계·의심·냉담·불신·짜증·실망·분노·적대·서먹함·우호·인정·\n"
    "   지지·신뢰·협력·친밀·화해 가운데 원문에 가장 가까운 것 하나나 둘을 \"·\"로 잇는다. 물건·열쇠·일을 믿고 맡기면 신뢰, 다툰 뒤 사과하고\n"
    "   다시 가까워지면 화해, 일·장비·시간을 함께 나누면 협력, 약속을 어겨 못 믿게 되면 불신, 화를 내며 끊거나 금지하면 분노다. 근거에는\n"
    "   그 태도를 드러낸 원문 낱말(\"믿고\", \"다시는 안 빌려줘\", \"미안해\")을 그대로 넣는다(예: \"신뢰 — 믿고 열쇠를 맡김\", \"분노·불신 —\n"
    "   다시는 안 빌려준다며 대여 금지\"). 원문에 드러난 태도만 쓰고 앞으로 어떻게 될지는 짐작하지 않는다. 태도가 바뀐 장면(다툼·사과·\n"
    "   화해·배신·인정·실망)은 반드시 그 방향의 relation 행을 새로 쓴다 — 조연 사이의 관계도 같다. relation 의 truth_status 는 언제나\n"
    "   confirmed 다(말로 드러난 태도도 드러난 태도다).\n"
    "3. 대화에 없는 것을 보태지 않는다. fact 의 value 는 원문에서 그 사실을 말한 구절을 글자 그대로 잘라 온 가장 짧은 토막이다(25자\n"
    "   안쪽) — 바꿔 말하지 않고, 어미·조사·문장부호를 고치지 않고, 여러 조각을 쉼표로 잇지 않고, 설명을 붙이지 않는다. \"~라는 말이 나옴\", \"~라고 함\" 같은 감싸는 말도 붙이지\n"
    "   않는다 — 말뿐이라는 것은 truth_status 와 speaker 가 나타낸다. 예: 원문이\n"
    "   \"나 다음 달에 부산으로 전학 가\"이면 value 는 \"다음 달에 부산으로 전학\"이다. 이름·숫자·시각·날짜도 원문 표기 그대로 쓴다(\"세 시\n"
    "   반\"을 \"3시 30분\"으로 바꾸지 않는다). 괄호 메모(\"(주장)\", \"(지문)\", \"(claimed)\" 같은 출처·상태 표시)를 넣지 않는다 — 출처와\n"
    "   상태는 다른 칸에 있다.\n"
    "4. subject 는 그 사실이 무엇에 관한 것인가다 — 말한 사람이 아니다. 인물이면 직함·호칭·가게 이름(\"사장님\", \"선배\")이 아니라\n"
    "   원문에 나온 온 이름을 쓴다. 물건을 주고받았으면 받은 인물을 subject 로, \"<준 인물>에게 받은 물건\"을 attribute 로 쓴다. \"배터리는 기계관 사물함에 있다\"는 말이면 subject 는 그 배터리,\n"
    "   attribute 는 \"보관 장소\"다. attribute 는 그 행이 답하는 물음을 구체적으로 적는다(\"생일 달\", \"알레르기 음식\", \"보관 장소\",\n"
    "   \"극중 이름\", \"진로 계획\", \"유나에게 한 약속\"). \"사정\"·\"정보\"·\"상태\"·\"약속\"·\"기타\"처럼 여러 사실이 한 칸에 몰려 서로 덮어쓰는\n"
    "   두루뭉술한 이름은 쓰지 않는다. 약속은 \"<상대 이름>에게 한 약속\"으로 상대마다 따로 쓴다.\n"
    "5. [기존 키]의 줄은 \"종류|주어|대상 또는 속성 = 값 (상태)\" 꼴이다. 같은 대상·같은 물음이면 그 주어와 대상·속성 표기를 글자 그대로\n"
    "   다시 쓴다 — 별명·호칭·\"그\"를 쓰거나 \"직업\"을 \"하는 일\"로 바꿔 새 키를 만들지 않는다. 사용자 쪽 인물은 사용자의 이야기 속 이름으로\n"
    "   쓴다. 물음이 다르면(다른 약속, 다른 물건) 기존 키를 빌려 쓰지 말고 새 키를 만든다 — 같은 키에 쓰면 옛 사실이 지워진다.\n"
    "6. 새로 적을 것만 쓴다 — 처음 나온 사실, 값이 바뀐 사실·관계, 뒤집힌 주장. [기존 키]에 같은 값으로 이미 있으면 다시 쓰지 않는다.\n"
    "   이 구간에 새로 적을 것이 없으면 facts 를 빈 목록으로 낸다. 행은 많아야 12개다. 우선순위: 관계 변화 → 비밀 → 뒤집힌 주장·정정 →\n"
    "   약속 → 사용자 인물에 관한 말 → 장소·시각·물건 정보.\n"
    "7. 대사와 서술을 가른다. 따옴표 안의 말은 대사이고, 그 밖은 서술이다. 사용자 줄의 따옴표 밖 글은 사용자가 자기 인물의 행동·선택을\n"
    "   적은 지문이다.\n"
    "8. fact 의 truth_status:\n"
    "   - confirmed: 진행자 서술이 일어난 일로 적은 것, 사용자 지문이 적은 것, 인물이 비밀로 털어놓은 자기 자신의 사정(10번), 그리고\n"
    "     그 사실의 주인이 남이 틀리게 말한 자기 일(생일·이름·물건)을 바로잡은 말.\n"
    "   - claimed: 그 밖에 대사로만 나온 것. 누가 했든 — 사용자 인물의 대사도 — 말한 것은 확인된 사실이 아니므로 claimed 다. 사용자\n"
    "     인물이 따옴표 안에서 자기에 대해 한 말은 무엇이든 claimed 다. 진행자 줄\n"
    "     속 인물이 말로 전한 장소·시각·남의 이력도 claimed 다.\n"
    "   - disproved: 앞선 주장([기존 키]의 claimed 값이나 이 구간 앞쪽 줄의 대사)이 서술·지문·다른 인물의 정정으로 틀렸다고 드러난 것.\n"
    "     같은 키로 틀린 그 값을 그대로 적은 disproved 행을 먼저 쓰고, 참인 값이 드러났으면 그 뒤에 같은 키로 참인 값 행을 쓴다(서술·\n"
    "     지문이 밝혔으면 confirmed). 참인 값 행의 value 에는 옛 값을 다시 적지 않는다.\n"
    "9. 사용자 인물이 한 거짓말이 같은 구간이나 뒤 구간의 지문·서술로 거짓이라고 드러나면, 거짓말 내용을 disproved 로, 진실을 같은 키의\n"
    "   confirmed 로 쓴다. 상대가 거짓말을 믿는다는 것은 상대 → 사용자 인물 relation 으로 쓸 수 있다. 아직 아무것도 드러나지 않은 대사는\n"
    "   claimed 로 둔다. 인물이 남을 속이는 경우도 같다.\n"
    "10. 비밀: 인물이 한 사람에게만 털어놓았다, \"비밀로 해 달라\"·\"아무한테도 말하지 마\"라고 했다, 다른 인물이 모르게 숨겼다, 혼자 보았다면\n"
    "    그 사실을 쓰고 known_by 에 아는 인물의 이름을 모두 쓴다(털어놓은 사람과 들은 사람 둘 다, 들은 사람이 사용자 인물이면 사용자의\n"
    "    이야기 속 이름). 이름은 subject 에 쓰는 것과 같은 성까지 붙은 온 이름이다 — \"태민\" 대신 \"오태민\". 사용자 인물에게 털어놓았으면 known_by 에\n"
    "    사용자의 이야기 속 이름을 반드시 넣는다. 그 밖에는 known_by 를 빈 목록으로 둔다 — 여럿이 있는 자리에서 한 말을 좁혀 적지 않는다.\n"
    "11. 사용자 인물에 관한 말은 작아 보여도 쓴다: 사용자 인물이 대사로 밝힌 자기 이력·취향·습관·가족·반려동물은 subject 를 사용자의\n"
    "    이야기 속 이름으로, claimed·asserted_by=user·speaker=사용자의 이야기 속 이름으로 쓴다. 인물이 사용자 인물에 대해 \"너 예전에\n"
    "    …했잖아\"처럼 한 말은 claimed·asserted_by=character·speaker=그 인물로 쓴다(사용자가 확인한 것이 아니다). 인물이 다른 인물(그\n"
    "    자리에 없는 사람도)의 과거·경력·가족·수상을 말하면 subject=그 인물, claimed, speaker=말한 인물로 쓴다.\n"
    "12. asserted_by 는 그 행의 근거 줄을 누가 썼는가다. 사용자 줄에서 나온 것은 대사든 지문이든 user, 진행자 줄 속 인물의 대사는\n"
    "    character, 진행자의 서술은 narration. 대사와 서술이 함께 근거면 truth_status 를 정한 쪽을 쓴다. speaker 는 대사면 말한 인물의\n"
    "    이름, 서술·지문이면 빈 문자열이다.\n"
    "13. importance 는 이 행이 나중에 다시 필요할 가능성이다 — 1(사소한 취향) ~ 5(관계의 큰 변화·약속·비밀·정체처럼 오래 남을 것).\n"
    "14. start_line·end_line 은 그 행의 근거가 드러난 [접힌 대화]의 줄 번호다. 한 줄이면 둘을 같게 쓴다.\n"
    "15. 행을 다 쓴 뒤 빠뜨리기 쉬운 것을 한 번 더 훑는다 — 이 구간에 아래가 있었는데 행이 없으면 더한다(12개 안에서 덜 중요한 행과\n"
    "    바꾼다).\n"
    "    - 누가 앞서 한 말을 \"아니야\", \"사실은\", \"잘못 알았네\"로 바로잡았다(8번 disproved → 참인 값).\n"
    "    - 인물이 사용자 인물에게만 털어놓은 자기 사정(10번).\n"
    "    - 인물이 다른 인물의 과거·경력·가족·수상을 말했다, 인물이 사용자 인물의 과거를 말했다(11번).\n"
    "    - 사용자 인물이 자기 이력·취향·가족·반려동물을 말했다(11번).\n"
    "    - 물건을 주고받았다, 약속을 했다, 장소·시각을 알려 줬다.\n"
    "16. [접힌 대화]의 줄만 근거로 삼는다. 수치 게이지나 작품 소개처럼 대화 줄에 없는 것은 쓰지 않는다."
)
FACT_USER_NAME_BODY = "사용자의 이야기 속 이름: {user_name}"
FACT_EXISTING_BODY = "[기존 키]\n{existing_facts}"
FACT_TURNS_BODY = "[접힌 대화]\n{turn_lines}"

# 사실 섹션. 생성 채널의 기억 노트·요약 섹션처럼 머리글 한 줄 + 문단 한 줄 + 값이다(문장 중간에서 줄을 바꾸지 않는다 — 모델에
# 가는 글에 뜻 없는 줄바꿈을 넣지 않는다). 우선순위의 섹션 이름은 같은 생성 채널의 실제 머리글과 같은 글자로 둔다 — 모델이 어느 섹션을 가리키는지 헷갈리지
# 않게. 사실 줄의 꼬리표("(사실 아님으로 밝혀짐)"·"(…만 앎)"·"(…의 말)")는 코드가 붙이고, 그 뜻을 여기서 설명한다.
FACTS_BODY = (
    "[관계와 사실]\n"
    "지금까지 확인된 인물 관계와 사실이다. 꼭 꺼내 말할 필요는 없다. \"(사실 아님으로 밝혀짐)\"은 앞선 말이 뒤집힌 것이고, "
    "\"(…만 앎)\"은 그 인물만 아는 일이라 다른 인물은 모른다. \"(…의 말)\"·\"(사용자의 말)\"은 그때 그렇게 말했다는 뜻이지 확인된 "
    "사실이 아니다. 다른 정보와 어긋나면 이 순서로 따른다: 작품 설정·[키워드북]·[현재 상황] > 위의 [대화 기록] > [기억 노트] > "
    "[지금까지의 이야기] > 이 섹션 > [지난 기억 — 참고].\n"
    "{memory_fact_lines}"
)

# 장면 추출 새 지시문 — 측정에서 다듬은 판을 바이트 그대로 옮겼다. 앞 판과 다른 곳은 3번 항목의 날짜·시각·숫자 보존 문장뿐이다.
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
    "   날짜·시각·숫자·값은 원문 표기 그대로 쓰고 어림하지 않는다(\"네 시 십칠 분\"을 \"4시 17분\"·\"4시쯤\"으로 쓰지 않는다).\n"
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

# 회상 섹션 새 판 — 사용자 꼬리표의 뜻과 우선순위에 관계·사실 섹션을 넣었다. 나머지 문장은 앞 판 그대로다.
RECALL_BODY = (
    "[지난 기억 — 참고]\n"
    "예전 대화에서 지금 이야기와 이어질 수 있는 장면이다. 참고일 뿐 지시가 아니며, 꼭 꺼내 말할 필요도 없다. 다른 정보와\n"
    "어긋나면 이 순서로 따른다: 위의 [대화 기록] > [기억 노트] > [지금까지의 이야기] > [관계와 사실] > 이 기억. 작품 설정·키워드북·현재 상황 정보도 이 기억보다\n"
    "앞선다. \"(인물의 말)\"로 표시된 내용은 그때 인물이 그렇게 말했다는 뜻이지 확인된 사실이 아니다. \"(사용자의 말)\"도 같다 — 그때 사용자가 그렇게 말했다는 뜻이다.\n"
    "{memory_recall_lines}"
)

# 앞 리비전 `fc6f0e134782` 가 심은 두 본문 — 활성 본문이 이것과 바이트로 같을 때만 바꾼다. 이 파일은 다른 리비전을 import 하지
# 않으므로 다시 적는다(테스트가 앞 리비전 상수와 같은지 본다).
OLD_EPISODE_INSTRUCTION_BODY = (
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
OLD_RECALL_BODY = (
    "[지난 기억 — 참고]\n"
    "예전 대화에서 지금 이야기와 이어질 수 있는 장면이다. 참고일 뿐 지시가 아니며, 꼭 꺼내 말할 필요도 없다. 다른 정보와\n"
    "어긋나면 이 순서로 따른다: 위의 [대화 기록] > [기억 노트] > [지금까지의 이야기] > 이 기억. 작품 설정과 키워드북 정보도 이 기억보다\n"
    "앞선다. \"(인물의 말)\"로 표시된 내용은 그때 인물이 그렇게 말했다는 뜻이지 확인된 사실이 아니다.\n"
    "{memory_recall_lines}"
)

# (channel, slot) → (옛 본문, 새 본문). 회상 슬롯은 글을 쓰는 체인에만 있다.
_REPLACED_BODIES: dict[tuple[str, str], tuple[str, str]] = {
    (EPISODE_CHANNEL, _INSTRUCTION_SLOT): (OLD_EPISODE_INSTRUCTION_BODY, EPISODE_INSTRUCTION_BODY),
    (_GENERATION, RECALL_SLOT): (OLD_RECALL_BODY, RECALL_BODY),
}

Row = tuple[str, str, str, str, str, bool, int]

# `(channel, scope, slot, variant, body, conditional, order)` — 새 채널은 기준 행이 없어 order 가 고정이다.
FACT_CHANNEL_ROWS: tuple[Row, ...] = (
    (FACT_CHANNEL, "both", _INSTRUCTION_SLOT, "", FACT_INSTRUCTION_BODY, False, 0),
    (FACT_CHANNEL, "both", "user_name", "", FACT_USER_NAME_BODY, True, 1),
    (FACT_CHANNEL, "both", "existing_facts", "", FACT_EXISTING_BODY, False, 2),
    (FACT_CHANNEL, "both", "turn_context", "", FACT_TURNS_BODY, False, 3),
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


def _replaced_slots(model: str) -> list[tuple[str, str]]:
    """그 체인에서 본문을 바꾸는 (channel, slot)."""
    return [key for key in _REPLACED_BODIES if model in _WRITING_MODELS or key[0] != _GENERATION]


def _assert_layout(rows: Sequence[Row], *, model: str, what: str, check_bodies: bool) -> int | None:
    """세트(또는 초안) 행이 이 리비전을 받을 모양인지 본다. 글을 쓰는 체인이면 `generation` 의 `memory_recall` order 를
    돌려주고, 판정 전용 체인이면 `None`. `check_bodies` 면(게시본) 바꾸는 본문이 옛 문안과 바이트로 같은지도 본다. 어긋나면
    `RuntimeError` — `what` 은 메시지에 쓸 세트 이름이다."""
    if any(row[0] == FACT_CHANNEL for row in rows):
        raise RuntimeError(f"[{what}] {FACT_CHANNEL} 채널 행이 이미 있다")
    if any(row[0] == _GENERATION and row[2] == FACTS_SLOT for row in rows):
        raise RuntimeError(f"[{what}] {_GENERATION} 채널에 {FACTS_SLOT} 행이 이미 있다")
    for channel, slot in _replaced_slots(model):
        matches = [row for row in rows if row[0] == channel and row[2] == slot]
        if len(matches) != 1:
            raise RuntimeError(f"[{what}] {channel} 채널의 {slot} 행이 정확히 하나가 아니다({len(matches)}개)")
        if check_bodies and matches[0][4] != _REPLACED_BODIES[(channel, slot)][0]:
            raise RuntimeError(
                f"[{what}] {channel} 채널의 {slot} 본문이 앞 리비전이 심은 문안과 다르다 — 어드민이 고친 운영 문안을 덮어쓰지"
                " 않는다. 고친 문안과 새 문안을 합친 뒤 다시 배포한다"
            )
    if model not in _WRITING_MODELS:
        return None
    return next(row[6] for row in rows if row[0] == _GENERATION and row[2] == RECALL_SLOT)


def _new_body(channel: str, slot: str, body: str) -> str:
    """바꾸는 슬롯이고 본문이 옛 문안과 같으면 새 문안, 아니면 그대로."""
    old_new = _REPLACED_BODIES.get((channel, slot))
    return old_new[1] if old_new is not None and body == old_new[0] else body


def _with_new_rows(rows: Sequence[Row], recall_order: int | None) -> list[Row]:
    """기존 행(두 본문은 새 문안) + 이 리비전의 행. `recall_order` 가 있으면(글을 쓰는 체인) 생성 채널에서 회상 슬롯부터 뒤 행을
    하나씩 밀고 사실 슬롯을 그 자리에 둔다."""
    result: list[Row] = []
    for channel, scope, slot, variant, body, conditional, order in rows:
        if recall_order is not None and channel == _GENERATION and order >= recall_order:
            order += 1
        result.append((channel, scope, slot, variant, _new_body(channel, slot, body), conditional, order))
    if recall_order is not None:
        result.append((_GENERATION, "both", FACTS_SLOT, "", FACTS_BODY, True, recall_order))
    result.extend(FACT_CHANNEL_ROWS)
    return result


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
        # 넣기 전에 네 체인을 모두 검사한다 — 하나라도 어긋나면 그 레인에는 아무것도 넣지 않은 채 멈춘다.
        source_rows = {model: _rows_of(conn, sources[model].id) for model in _MODELS}
        recall_orders = {
            model: _assert_layout(source_rows[model], model=model, what=f"{lane}/{model}", check_bodies=True)
            for model in _MODELS
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
                rows=_with_new_rows(source_rows[model], recall_orders[model]),
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


_SWAP_BODY_SQL = sa.text(
    "UPDATE prompt_sections SET body = :to_body"
    " WHERE prompt_set_id = :id AND channel = :channel AND slot = :slot AND body = :from_body"
)


def _patch_drafts(conn: Connection) -> list[tuple[str, str]]:
    """초안이 있는 체인은 초안 **자신의** 행으로 모양 가정을 검사한 뒤 새 행을 제자리에서 넣고(글을 쓰는 체인은 회상 슬롯부터
    뒤 행의 order 를 민다), 바꾸는 두 본문은 옛 문안과 같을 때만 바꾼다(위 docstring). 손댄 (레인, 모델) 목록을 돌려준다. `op` 를
    쓰지 않는 이유는 `seed_published_sets` 와 같다."""
    patched: list[tuple[str, str]] = []
    for lane in _LANES:
        for model in _MODELS:
            draft_id = conn.execute(_DRAFT_SQL, {"lane": lane, "model": model}).scalar_one_or_none()
            if draft_id is None:
                continue
            recall_order = _assert_layout(
                _rows_of(conn, draft_id), model=model, what=f"{lane}/{model} 초안", check_bodies=False
            )
            for channel, slot in _replaced_slots(model):
                old_body, new_body = _REPLACED_BODIES[(channel, slot)]
                conn.execute(
                    _SWAP_BODY_SQL,
                    {"id": draft_id, "channel": channel, "slot": slot, "from_body": old_body, "to_body": new_body},
                )
            new_rows = list(FACT_CHANNEL_ROWS)
            if recall_order is not None:
                conn.execute(
                    sa.text(
                        'UPDATE prompt_sections SET "order" = "order" + 1'
                        ' WHERE prompt_set_id = :id AND channel = :channel AND "order" >= :recall'
                    ),
                    {"id": draft_id, "channel": _GENERATION, "recall": recall_order},
                )
                new_rows.append((_GENERATION, "both", FACTS_SLOT, "", FACTS_BODY, True, recall_order))
            conn.execute(
                sa.insert(prompt_sections_table),
                _section_dicts(new_rows, prefix="draft:", lane=lane, model=model, set_id=draft_id),
            )
            patched.append((lane, model))
    return patched


def upgrade() -> None:
    """Upgrade schema."""
    # 배포 중에도 떠 있는 API 가 prompt_sets 를 읽고 쓴다. 이 리비전은 행만 넣고 초안 몇 행만 고쳐 오래 쥐는 락이 없지만, 다른
    # 트랜잭션 뒤에서 끝없이 기다리지 않고 5초 안에 실패해 배포가 멈추게 첫 문장으로 건다.
    op.execute("SET LOCAL lock_timeout = '5s'")
    bind = op.get_bind()
    seed_published_sets(bind)
    _patch_drafts(bind)


def _delete_draft_rows(conn: Connection) -> None:
    """초안의 `memory_fact` 행과 사실 슬롯 행을 지우고 사실 슬롯 뒤 생성 행의 order 를 −1 하며, 두 본문이 새 문안이면 옛 문안으로
    되돌린다."""
    draft_ids = sa.text(
        "SELECT id FROM prompt_sets WHERE status = 'draft' AND lane IN :lanes"
    ).bindparams(sa.bindparam("lanes", expanding=True))
    for draft_id in conn.execute(draft_ids, {"lanes": list(_LANES)}).scalars().all():
        conn.execute(
            sa.text("DELETE FROM prompt_sections WHERE prompt_set_id = :id AND channel = :channel"),
            {"id": draft_id, "channel": FACT_CHANNEL},
        )
        facts_orders = conn.execute(
            sa.text(
                'DELETE FROM prompt_sections WHERE prompt_set_id = :id AND channel = :channel AND slot = :slot'
                ' RETURNING "order"'
            ),
            {"id": draft_id, "channel": _GENERATION, "slot": FACTS_SLOT},
        ).scalars().all()
        for facts_order in sorted(facts_orders, reverse=True):
            conn.execute(
                sa.text(
                    'UPDATE prompt_sections SET "order" = "order" - 1'
                    ' WHERE prompt_set_id = :id AND channel = :channel AND "order" > :facts'
                ),
                {"id": draft_id, "channel": _GENERATION, "facts": facts_order},
            )
        for (channel, slot), (old_body, new_body) in _REPLACED_BODIES.items():
            conn.execute(
                _SWAP_BODY_SQL,
                {"id": draft_id, "channel": channel, "slot": slot, "from_body": new_body, "to_body": old_body},
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
            f"시드 뒤에 어드민이 게시한 세트가 있다({', '.join(later)}) — 되돌리면 관계·사실 기억 행이 든 그 세트가 활성으로 남아"
            " 이전 코드의 그 체인 게시가 막힌다. 아무것도 지우지 않았다"
        )

    seed_ids = list(NEW_SET_IDS.values())
    conn.execute(sa.delete(prompt_sections_table).where(prompt_sections_table.c.prompt_set_id.in_(seed_ids)))
    conn.execute(sa.delete(prompt_sets_table).where(prompt_sets_table.c.id.in_(seed_ids)))
    _delete_draft_rows(conn)


def downgrade() -> None:
    """Downgrade schema."""
    delete_seeded_rows(op.get_bind())
