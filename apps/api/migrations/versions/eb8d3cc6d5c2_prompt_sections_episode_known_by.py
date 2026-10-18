"""prompt sections episode extraction known_by rules

Revision ID: eb8d3cc6d5c2
Revises: 0346abdbcc92
Create Date: 2026-10-18 23:00:00.000000

장면 기억 추출 지시문(`memory_episode`/`instruction`)을 장면에 아는 인물을 적게 하는 판으로 바꾼다. 같은 배포에서 장면 추출 결과
스키마에 아는 인물 칸(`known_by`)이 생기는데, 규칙 없이 칸만 생기면 모델이 그 칸을 제멋대로 채운 장면 행이 운영에 쌓이므로 문안과
스키마를 함께 바꾼다. 새 판은 앞 판의 줄을 순서·바이트 그대로 두고 두 덩어리를 더한다.
- 말한 인물 규칙(4번 항목 끝): 말한 사람 칸에 인물을 두는 건 그 인물의 대사에만 나오고 확인되지 않은 주장을 담은 장면뿐이다.
  눈앞에서 실제로 벌어진 일은 서술 장면으로 남겨, 회상할 때 누군가의 주장이 사실처럼 섞여 들지 않게 한다.
- 아는 인물 규칙(새 10번)과 점검 목록(새 11번): 혼자 보거나 들은 일, 한 사람에게만 털어놓은 일, 숨긴 일, 남이 몰래 본 비밀이면 그 일을
  아는 인물을 모두 적고, 여럿이 함께 있는 자리에서 드러난 일만 빈 목록으로 둔다. 그 장면에 실제로 있었던 인물만 넣는다(대사 속에서
  이름만 불린 인물은 넣지 않는다). 사용자 쪽 인물은 사용자의 이야기 속 이름으로 적는다 — 사실 추출 지시문과 같은 표기라, 읽는 쪽이
  사용자 표기를 같은 규칙으로 걸러 낸다.

**효과가 바로 난다**: 장면 추출은 운영에서 켜져 있어, 이 리비전이 적용된 뒤의 다음 접기부터 추출 호출이 새 문안으로 렌더되고 새
결과 스키마로 아는 인물 칸을 받는다. 생성 프롬프트에는 이 채널이 실리지 않으므로 생성 쪽 바이트는 바뀌지 않는다.

**심는 것**: story·character 레인마다 네 체인(gemini·sonnet·opus·haiku)에 새 published 세트 하나씩, 모두 여덟. 장면 추출 채널은 네
체인 모두에 있다 — 추출 모델 설정이 어느 체인을 고르든 그 세트의 문안이 바뀌어야 한다.

**새 세트는 그 체인 활성 세트의 바이트 사본에서 장면 추출 지시문 하나만 바꾼 것이다** — 라벨·다른 모든 행(운영자가 어드민에서
고친 문안, 얼려 둔 소설 행 포함)과 order 가 그대로 옮겨진다. 행을 더하거나 빼지 않는다. **게시된 세트는 고치지 않는다.**

**지시문은 활성 본문이 그 문안을 마지막으로 바꾼 리비전 `5cab2abe4e7b` 의 문안(`OLD_EPISODE_INSTRUCTION_BODY`)과 바이트로 같을
때만 바꾼다.** 다르면 어드민이 고쳐 게시한 운영 문안이라 조용히 덮어쓰지 않고 `RuntimeError` 로 배포를 멈춘다 — 사람이 고친 문안과
새 문안을 합칠지 판단해야 한다.

**`published_at` — 두 활성 조회 규칙을 함께 만족시킨다**(앞의 기억 문안 리비전들과 같은 규칙).
- 레인만 보는 조회(모델 열을 모르는 원시 SQL)는 레인의 최신 게시본을 고른다 — 새 Gemini 세트는 파이썬 `max(now, 원본 + 1초)`.
- 모델로 거르는 조회(`load_active_prompt_set`)는 (레인, 모델)마다 최신 게시본을 고른다 — sonnet·opus·haiku 의 새 세트는 (그 체인
  활성 시각, 그 레인 새 Gemini 세트 시각)의 **중간값**. 사이에 둘 시각이 없으면 `RuntimeError`.
- 삽입 뒤 두 규칙으로 다시 SELECT 해 확인한다. 어긋나면 `RuntimeError`.

**가정이 어긋나면 배포를 멈춘다**(`RuntimeError`, 체인이 한 트랜잭션이라 앞 리비전까지 함께 롤백된다): 이 리비전의 세트가 이미
있을 때, 레인만 보는 조회가 이미 Gemini 가 아닌 세트를 집을 때, 활성 세트에 `memory_episode` 의 `instruction` 행이 정확히 하나가
아닐 때, 그 본문이 앞 리비전 문안과 다를 때. 한 레인의 네 체인을 모두 검사한 뒤에 넣는다.

**초안**: 초안은 지시문이 앞 리비전 문안과 같을 때만 새 문안으로 바꾸고, 다르면(행이 없거나 운영자가 고치던 중이면) 그대로 둔다
— 초안은 고치던 작업이라 덮어쓰면 그 작업이 사라지고, 초안 하나 때문에 배포를 멈출 일도 아니다. 행 모양은 바뀌지 않아 초안의
게시 검증에는 영향이 없다.

**PK**: 세트는 리터럴 UUID(`NEW_SET_IDS`), 섹션은 새 namespace 의 `uuid5("{lane}:{model}:{channel}:{scope}:{slot}:{variant}")`.
`version` 은 전 레인·전 모델 published 최대 + 1 을 (story, character) × (gemini, sonnet, opus, haiku) 순서로 매긴다(어드민 게시와
같은 규칙).

**옛 이미지가 이 데이터 위에서 도는 구간**(배포 중 겹침, 이미지만 되돌린 동안): 슬롯·자리표시자·행 집합이 앞 리비전과 같고(두
지시문 모두 자리표시자가 없다) 본문 글만 바뀌므로 옛 코드도 그대로 렌더하고, 옛 코드의 어드민 게시 검증도 새 세트를 통과시킨다.
다만 옛 코드의 결과 스키마에는 아는 인물 칸이 없어, 그 구간의 추출은 새 문안을 받고도 그 칸을 돌려줄 자리가 없다 — 장면 행의 칸은
NULL(공개이거나 알 수 없음)로 남고, 말한 인물 규칙만 효과가 난다.

⚠️ **운영 메모**:
- 마이그레이션은 활성 세트 캐시를 지우지 않는다 — 배포 직후 최대 300초 동안 옛 세트(옛 지시문)로 추출할 수 있다. 그동안 새 코드의
  추출은 옛 문안에 새 스키마라, 규칙 없는 아는 인물 칸이 그 몇 분 동안의 장면 행에 들어갈 수 있다.
- 🔴 **시드를 손으로 지우지 않는다.** 되돌리려면 아래 `downgrade` 를 쓴다.
- 🔴 **프롬프트 옛 버전을 통째로 복원하지 않는다** — 현재 활성본에서 바뀐 섹션만 고친다.

**롤백 순서**: 이미지만 되돌리면 새 지시문이 남은 채 옛 코드가 돈다(렌더는 문제없고 아는 인물 칸은 NULL 로 남는다). 옛 지시문까지
되돌려야 하면 **이 리비전 파일이 있는 이미지로** `downgrade` 를 실행한다 — 새 이미지가 도는 채로 지시문만 되돌리면 규칙 없는 아는
인물 칸이 다시 쌓이므로, `downgrade` 뒤에는 이미지도 되돌린다.

`downgrade()`(`delete_seeded_rows`): 시드 뒤에 어드민이 여덟 체인 중 하나에 새 버전을 게시했으면 아무것도 지우지 않고
`RuntimeError` 로 멈춘다 — 되돌리면 그 게시본이 활성으로 남아 되돌린 뜻이 사라지고, 무엇을 버릴지는 사람이 정해야 한다. 없으면
리터럴 시드의 섹션 → 세트를 지운다 — 이전 활성 세트는 처음부터 옛 지시문을 갖고 있다. 초안은 지시문이 이 리비전의 새 문안과
같으면 옛 문안으로 되돌린다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례). 테스트(`tests/test_episode_known_by_prompt_migration.py`)가 이 모듈을
`importlib` 로 불러 `seed_published_sets`·`_patch_drafts`·`delete_seeded_rows`·`_delete_draft_rows` 를 직접 부른다.
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'eb8d3cc6d5c2'
down_revision: str | Sequence[str] | None = '0346abdbcc92'
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
# 장면 추출 채널이 있는 네 체인. Gemini 가 맨 앞이어야 한다(다른 체인의 게시 시각이 새 Gemini 세트 시각에 기댄다).
_MODELS: tuple[str, ...] = (_GEMINI, "sonnet", "opus", "haiku")

# 리터럴 UUID — 작성 시점에 uuid.uuid4()를 한 번씩 실행해 뽑았다.
NEW_SET_IDS: dict[tuple[str, str], uuid.UUID] = {
    ("story", "gemini"): uuid.UUID('29c192e3-6c3b-42c5-9dbf-76e10e9aefc0'),
    ("story", "sonnet"): uuid.UUID('62702bc5-aa69-4c71-b1a2-26d83e145873'),
    ("story", "opus"): uuid.UUID('8b71c446-42ad-49c9-b3e4-2b39cfcffa4e'),
    ("story", "haiku"): uuid.UUID('6d77ad41-b44b-4ada-a949-0736f9660a44'),
    ("character", "gemini"): uuid.UUID('799ddb7c-d22e-46b5-b520-3f3079e773f0'),
    ("character", "sonnet"): uuid.UUID('22f5b6d4-4a3c-4c3d-9101-1ae7ea8ef27d'),
    ("character", "opus"): uuid.UUID('0e4c5949-a421-437a-be81-1a240a61c6c1'),
    ("character", "haiku"): uuid.UUID('daa55534-26a8-42d4-aa5d-0f498533d6da'),
}
_SECTION_ID_NAMESPACE = uuid.UUID('7d69c1bf-7852-41bb-8003-3e60a13baa5a')

# 적용된 뒤에는 DB에 영구히 남는 값이라 문서명·번호를 넣지 않는다.
_NOTE = "장면 추출 지시문의 아는 인물·말한 인물 규칙 교체(활성 세트 사본)"

EPISODE_CHANNEL = "memory_episode"
INSTRUCTION_SLOT = "instruction"

# 장면 추출 지시문 새 판 — 측정에서 고른 판을 바이트 그대로 옮겼다(측정이 지시문 행에 넣은 파일 그대로, 끝 줄바꿈 없음).
# 앞 판의 규칙에 장면을 아는 인물(known_by) 규칙과, 대사 속 확인 안 된 주장만 말한 인물로 다는 화자 규칙을 더했다.
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
    "   서술과 미확인 주장을 한 장면에 섞지 않는다. 미확인 주장은 인물이 대사로 말했지만 서술·지문으로 일어났다고 드러나지 않은\n"
    "   사실이다(지난 일, 그 자리에 없는 사람의 일, 사용자 인물에 대한 말, 소문). 행동·사건이 이어지는 서술 장면 한가운데서 인물이\n"
    "   그런 주장을 길게 꺼내면, 그 주고받음을 따로 떼어 asserted_by=character 장면으로 두고(1번의 10개 안에서), 서술 장면의 detail 에는\n"
    "   일어난 일만 남긴다. 따로 떼기에 짧은 주장은 서술 장면 detail 에 쓰지 않고 그 장면 evidence 에도 옮기지 않는다.\n"
    "5. nouns 는 detail 속 고유명사·구체 명사를 원문 표기 그대로, 조사를 떼고 적는다. keywords 는 이 장면을 다시 찾을 때 쓸 만한\n"
    "   낱말(무엇을 했는가) 몇 개다.\n"
    "6. evidence 는 핵심 사실이 드러난 원문을 한두 줄, 짧게 그대로 옮긴다(줄 번호는 빼고).\n"
    "7. importance 는 이 장면이 나중에 다시 나올 가능성이다 — 1(사소한 일상) ~ 5(관계·약속·비밀처럼 오래 남을 일).\n"
    "8. start_line·end_line 은 그 장면이 시작하고 끝나는 [접힌 대화]의 줄 번호다. 첫 장면은 1에서 시작하고, 마지막 장면은\n"
    "   [접힌 대화]의 마지막 줄 번호에서 끝난다.\n"
    "9. [앞 구간의 마지막 장면]은 제목을 맞추는 데만 쓴다. 이 구간의 첫 장면이 그 장면에서 이어지면 같은 제목을 쓰고, detail 에는\n"
    "   이 구간의 줄에서 나온 것을 적는다. 모든 장면의 detail 은 비우지 않는다 — 적을 것이 없는 장면은 따로 만들지 말고 이웃한\n"
    "   장면에 합친다.\n"
    "10. known_by 는 그 장면에서 일어난 일을 아는 인물의 이름 목록이다 — 반드시 채울지 따진다. 혼자 보거나 들은 일(주인 없는 사건도),\n"
    "    한 사람에게만 털어놓은 일, 남몰래 숨긴 일, 남이 몰래 본 비밀이면 그 일을 아는 인물을 모두 적는다: 본 인물, 털어놓은 인물과\n"
    "    들은 인물, 비밀의 주인. 아는 사람이 사용자 인물이면 사용자의 이야기 속 이름을 적는다. 여럿이 함께 있는 자리에서 드러난 일만\n"
    "    빈 목록이다. 그 장면에 실제로 있었던 인물만 넣는다 — 대사 속에서 이름만 불린 인물은 넣지 않는다.\n"
    "11. 장면을 다 쓴 뒤 한 번 더 훑는다.\n"
    "    - 인물이 혼자 있거나 둘만 있던 장면, 털어놓거나 숨긴 장면에 known_by 가 비어 있지 않은가.\n"
    "    - known_by 에 그 자리에 없던 인물(이름만 나온 인물)이 들어 있지 않은가.\n"
    "    - narration 장면의 detail 에 인물의 확인 안 된 말이 섞여 있지 않은가 — 섞였으면 그 말을 빼거나 장면을 가른다."
)

# 앞 리비전 `5cab2abe4e7b` 가 심은 장면 추출 지시문 — 활성 본문이 이것과 바이트로 같을 때만 바꾼다. 이 파일은 다른
# 리비전을 import 하지 않으므로 다시 적는다(테스트가 앞 리비전 상수와 같은지 본다).
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


def _assert_instruction_row(rows: Sequence[Row], *, what: str) -> None:
    """게시본에 장면 추출 지시문 행이 정확히 하나이고 그 본문이 앞 리비전 문안과 바이트로 같은지 본다. 어긋나면 `RuntimeError` —
    `what` 은 메시지에 쓸 세트 이름이다."""
    matches = [row for row in rows if row[0] == EPISODE_CHANNEL and row[2] == INSTRUCTION_SLOT]
    if len(matches) != 1:
        raise RuntimeError(f"[{what}] {EPISODE_CHANNEL} 채널의 {INSTRUCTION_SLOT} 행이 정확히 하나가 아니다({len(matches)}개)")
    if matches[0][4] != OLD_EPISODE_INSTRUCTION_BODY:
        raise RuntimeError(
            f"[{what}] {EPISODE_CHANNEL} 채널의 {INSTRUCTION_SLOT} 본문이 앞 리비전이 심은 문안과 다르다 — 어드민이 고친 운영 문안을"
            " 덮어쓰지 않는다. 고친 문안과 새 문안을 합친 뒤 다시 배포한다"
        )


def _with_new_instruction(rows: Sequence[Row]) -> list[Row]:
    """기존 행 그대로, 장면 추출 지시문만 새 문안."""
    return [
        (
            channel,
            scope,
            slot,
            variant,
            EPISODE_INSTRUCTION_BODY if (channel, slot) == (EPISODE_CHANNEL, INSTRUCTION_SLOT) else body,
            cond,
            order,
        )
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
    """레인마다 네 체인에 새 세트를 넣고, 두 활성 조회 규칙으로 다시 확인한다.

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
        # 넣기 전에 네 체인을 모두 검사한다 — 하나라도 어긋나면 그 레인에는 아무것도 넣지 않은 채 멈춘다.
        source_rows = {model: _rows_of(conn, sources[model].id) for model in _MODELS}
        for model in _MODELS:
            _assert_instruction_row(source_rows[model], what=f"{lane}/{model}")

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
                rows=_with_new_instruction(source_rows[model]),
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


def _swap_draft_instruction(conn: Connection, *, from_body: str, to_body: str) -> list[tuple[str, str]]:
    """초안의 장면 추출 지시문이 `from_body` 와 같으면 `to_body` 로 바꾸고, 바꾼 (레인, 모델) 목록을 돌려준다."""
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
                    "channel": EPISODE_CHANNEL,
                    "slot": INSTRUCTION_SLOT,
                    "from_body": from_body,
                    "to_body": to_body,
                },
            )
            if result.rowcount:
                swapped.append((lane, model))
    return swapped


def _patch_drafts(conn: Connection) -> list[tuple[str, str]]:
    """초안의 장면 추출 지시문이 앞 리비전 문안과 같으면 새 문안으로 바꾼다(위 docstring). `op` 를 쓰지 않는 이유는
    `seed_published_sets` 와 같다."""
    return _swap_draft_instruction(conn, from_body=OLD_EPISODE_INSTRUCTION_BODY, to_body=EPISODE_INSTRUCTION_BODY)


def _delete_draft_rows(conn: Connection) -> list[tuple[str, str]]:
    """초안의 장면 추출 지시문이 이 리비전의 새 문안이면 옛 문안으로 되돌린다."""
    return _swap_draft_instruction(conn, from_body=EPISODE_INSTRUCTION_BODY, to_body=OLD_EPISODE_INSTRUCTION_BODY)


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
