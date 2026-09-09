"""prompt sets and sections

Revision ID: bd258b26c34a
Revises: 45c1a3d8b69e
Create Date: 2026-09-10 00:07:40.066022

prompt-db-goal-prompt.md §4, §6 (1단계) — 프롬프트 문안을 코드 상수에서 DB로 옮기는
첫 단계. 테이블 둘(`prompt_sets`/`prompt_sections`)을 만들고 같은 리비전에 지금
코드가 실제로 쓰는 문안을 초기 세트로 시드한다. 렌더러 교체(2단계)는 이 런의 범위
밖이다 — 지금은 상수도 그대로 남아 있고 아무 호출부도 이 테이블을 읽지 않는다.

**시드 문안은 손으로 옮겨 적지 않았다.** `chat/prompt_builder.py`의 `_COMMON_RULES`·
`STORY_CHAT_SYSTEM_INSTRUCTION`·`CHARACTER_CHAT_SYSTEM_INSTRUCTION`·
`_TEMPLATE_INSTRUCTIONS`와, `build_*`/`content/publish.py`의 실제 호출 결과를
스크래치 스크립트로 쪼개 슬롯별 body를 뽑아낸 뒤 그 출력을 그대로 붙여넣었다
(`system` 채널은 `_COMMON_RULES.split("\\n\\n")`로 5블록, 나머지 채널은 함수를
호출해 `"\\n\\n"` 섹션으로 쪼개고 각 섹션의 헤더 줄을 취하는 방식). `tests/
test_prompt_seed.py`가 시드된 `system` 채널 7슬롯을 `scope`로 거르고 `order`로
정렬해 이은 결과가 `system_instruction_for()`의 실제 출력 6종과 바이트 단위로
같음을 재확인한다(D-13).

**부분 유니크 인덱스 2개**는 `legal_documents`(`5bef71fc8f50`) 선례를 그대로
따른다 — `postgresql_where`에 bare `Mapped` 컬럼을 주면 autogenerate가 만드는
소스에 `MappedColumn` 객체 repr이 박혀 `SyntaxError`가 난다(실측) — 모델에서
`status == "draft"`처럼 명시적 불리언 식을 준 덕에 여기 렌더링된 `sa.text(...)`가
정상이다.

**`prompt_sections`의 유니크 키는 `(prompt_set_id, channel, slot, variant)`가
아니라 `(prompt_set_id, channel, scope, slot, variant)`다.** 목표 문서
(prompt-db-goal-prompt.md) §4-1의 문면은 scope를 뺀 4열이지만, 그 문서 §4-2가
확정한 시드 표를 `(channel, slot, variant)`만으로 묶어 보면 **충돌 그룹이 둘**이다
— `('system', 'self_definition', '')`가 `scope=story`/`character` 두 행,
`('publish_filter', 'intro_instruction', '')`가 `scope=character`/`story` 두 행
(실제 시드로 재현 확인). scope 없이 그대로 만들면 이 네 행이 유니크 위반으로
삽입되지 않는다(dev Postgres에서 실측: `duplicate key value violates unique
constraint`). scope를 포함한 5열 키로는 충돌이 없다. 문서의 두 확정 사항이 서로
모순돼 실행 가능한 쪽(§4-2 시드 표)을 따랐다.

**`variant`를 nullable로 두지 않는다** — 기본값 `''`. Postgres UNIQUE는 NULL끼리
중복으로 보지 않으므로 nullable이면 `(set, channel, scope, slot, NULL)` 행이
무한히 들어가 `ix_prompt_sections_set_channel_scope_slot_variant`가 무력화된다.

**시드 삽입은 `op.bulk_insert` + 경량 `sa.table(...)`**(약관 시드 `c49014ae5b62`
선례) — 값이 바인드 파라미터로 가므로 한글 본문의 따옴표·괄호를 이스케이프할
필요가 없다. PK는 이 파일 작성 시점에 `uuid.uuid4()`를 한 번 실행해 뽑은 뒤
하드코딩한 리터럴이다(마이그레이션 실행 시점에는 `uuid4()`를 호출하지 않는다 —
환경마다 값이 달라지는 것을 막기 위해서다).

`downgrade()`가 테이블을 통째로 drop하므로 시드 행을 지우는 별도 DELETE는
필요 없다 — 이 리비전이 만든 테이블에는 이 리비전이 심은 행만 있다.
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'bd258b26c34a'
down_revision: str | Sequence[str] | None = '45c1a3d8b69e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PROMPT_SET_ID = uuid.UUID('9c503c40-2925-4d94-b240-affa9c0166b3')

prompt_sets_table = sa.table(
    "prompt_sets",
    sa.column("id", sa.Uuid()),
    sa.column("version", sa.Text()),
    sa.column("status", sa.Text()),
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

# 슬롯 정의는 prompt-db-progress.md §B(16/16 바이트 동일 검증 완료)와 정확히 같다.
# body는 스크래치 스크립트가 실제 코드 상수/함수 호출에서 뽑아낸 문자열이다(위 docstring).
SEED_SECTIONS: list[dict[str, object]] = [
    {
        "id": uuid.UUID('3d522809-1fb0-4e2e-9086-e14b1bac064a'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'system',
        "scope": 'story',
        "slot": 'self_definition',
        "variant": '',
        "order": 1,
        "conditional": False,
        "body": '너는 사용자와 함께 이야기를 만들어 가는 화자다. 장면을 서술하고 그 안의 인물들을 연기한다.\n아래는 어떤 작품에서도 지켜야 하는 공통 규칙이다.',
    },
    {
        "id": uuid.UUID('9aed3f24-5d08-4eb0-8f53-9dc4b11f2bc7'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'system',
        "scope": 'character',
        "slot": 'self_definition',
        "variant": '',
        "order": 1,
        "conditional": False,
        "body": '너는 아래 설정으로 주어진 캐릭터 본인이다. 해설자가 아니라 그 인물로서 사용자와 일대일로 대화한다.\n아래는 어떤 캐릭터에게나 적용되는 공통 규칙이다.',
    },
    {
        "id": uuid.UUID('85f6d13f-55cd-42eb-9c26-e6c35e837bf9'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'system',
        "scope": 'both',
        "slot": 'rule_response_format',
        "variant": '',
        "order": 2,
        "conditional": False,
        "body": '[응답 형식]\n응답을 화자 이름이나 역할 표시로 시작하지 않는다. 첫 글자부터 바로 서술이거나 대사다.',
    },
    {
        "id": uuid.UUID('14edbbca-d0bd-4406-b540-e8f39cd0d8b3'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'system',
        "scope": 'both',
        "slot": 'rule_user_agency',
        "variant": '',
        "order": 3,
        "conditional": False,
        "body": '[사용자의 몫은 사용자가 정한다]\n사용자의 대사·행동·선택·감정을 대신 쓰지 않는다. 사용자가 하지 않은 말을 인용하거나 했다고 단정하지 않는다.',
    },
    {
        "id": uuid.UUID('a25eae1c-ec27-4e23-9d52-ac0b568169c9'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'system',
        "scope": 'both',
        "slot": 'rule_open_turn',
        "variant": '',
        "order": 4,
        "conditional": False,
        "body": '[턴을 열어 둔다]\n매 턴은 사용자가 다음에 할 수 있는 것을 최소 하나 남긴다 — 인물이 원하는 것, 방금 변한 상황, 새로 드러난 사실 중 하나면 된다. 인물이 냉담하거나 말을 아끼는 것은 작품의 자유다. 그 경우에도 장면은 움직인다: 다른 인물, 배경, 사용자가 손댈 수 있는 무언가 중 하나가 반응한다. 장면은 항상 사용자의 다음 행동을 기다리는 상태로 끝난다.',
    },
    {
        "id": uuid.UUID('d1474ffd-8680-496e-b4ac-01f500b7597b'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'system',
        "scope": 'both',
        "slot": 'rule_rating',
        "variant": '',
        "order": 5,
        "conditional": False,
        "body": '[수위]\n전연령 서비스다. 선정적 묘사, 노골적인 신체 훼손, 자해 방법 묘사를 하지 않는다. 이 항목은 작품 설정보다 우선한다.',
    },
    {
        "id": uuid.UUID('daa509f0-c6fe-4851-94e0-5777569221cb'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'system',
        "scope": 'story',
        "slot": 'template_instruction',
        "variant": 'basic',
        "order": 6,
        "conditional": False,
        "body": '매 턴 상황이 한 걸음 움직이고, 다음 장면으로 이어질 실마리를 남긴다.',
    },
    {
        "id": uuid.UUID('bf270703-b940-45b1-8a87-09225bcfbf16'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'system',
        "scope": 'story',
        "slot": 'template_instruction',
        "variant": 'emotional',
        "order": 6,
        "conditional": False,
        "body": '인물의 감정 변화는 장면 안의 단서로 드러난다 — 표정, 손짓, 목소리의 결. 침묵도 반응이며, 그 침묵이 무엇을 뜻하는지 장면이 알려 준다.',
    },
    {
        "id": uuid.UUID('fd839e07-55ed-4b24-9116-78f3ee930141'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'system',
        "scope": 'story',
        "slot": 'template_instruction',
        "variant": 'simulation',
        "order": 6,
        "conditional": False,
        "body": '이번 턴에 무엇이 변했는지 장면 안에 명시하고, 지금 손댈 수 있는 것이 장면 안에 놓여 있다.',
    },
    {
        "id": uuid.UUID('c38ee5c8-3bc1-4a9a-9be8-246dca0feb07'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'system',
        "scope": 'story',
        "slot": 'template_instruction',
        "variant": 'custom',
        "order": 6,
        "conditional": False,
        "body": '매 턴 상황이 한 걸음 움직이고, 다음 장면으로 이어질 실마리를 남긴다.',
    },
    {
        "id": uuid.UUID('e9d31239-06d0-498a-bfb7-c062bff59d48'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'system',
        "scope": 'both',
        "slot": 'priority_tail',
        "variant": '',
        "order": 7,
        "conditional": False,
        "body": '작품별 설정이 위 규칙보다 구체적인 지시를 하면 그 지시를 따른다(수위 항목은 예외).',
    },
    {
        "id": uuid.UUID('d73c2e91-1b7e-423f-b822-4ded4182ff57'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'generation',
        "scope": 'character',
        "slot": 'character_prompt',
        "variant": '',
        "order": 1,
        "conditional": False,
        "body": '{character_prompt}',
    },
    {
        "id": uuid.UUID('e36b5e69-8e17-4cf4-a00c-ac5ce1f6a1d1'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'generation',
        "scope": 'story',
        "slot": 'base_content',
        "variant": '',
        "order": 1,
        "conditional": True,
        "body": '{setting_text}',
    },
    {
        "id": uuid.UUID('6f206556-c5a3-4096-a867-6a3575f5bd88'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'generation',
        "scope": 'story',
        "slot": 'base_content',
        "variant": 'custom',
        "order": 1,
        "conditional": True,
        "body": '{custom_prompt}',
    },
    {
        "id": uuid.UUID('356758f6-e3a8-4d0d-8d62-4345763feea7'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'generation',
        "scope": 'character',
        "slot": 'example_dialogues',
        "variant": '',
        "order": 2,
        "conditional": True,
        "body": '[말투 예시]\n{example_lines}',
    },
    {
        "id": uuid.UUID('3a4652a4-9ec3-40dc-970b-1227a3614604'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'generation',
        "scope": 'story',
        "slot": 'rules',
        "variant": '',
        "order": 2,
        "conditional": True,
        "body": '[규칙]\n{rules}',
    },
    {
        "id": uuid.UUID('7c86547f-e4bf-49ee-9681-1fabc8c8c438'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'generation',
        "scope": 'story',
        "slot": 'user_goal',
        "variant": '',
        "order": 3,
        "conditional": True,
        "body": '[사용자의 역할과 목표]\n{user_goal}',
    },
    {
        "id": uuid.UUID('3b0b0ac9-baa5-450f-aa3a-bc0346624c8c'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'generation',
        "scope": 'story',
        "slot": 'development_examples',
        "variant": '',
        "order": 4,
        "conditional": True,
        "body": '[전개 예시]\n{example_lines}',
    },
    {
        "id": uuid.UUID('d3fde8cb-ab04-407b-91a6-6111d618d802'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'generation',
        "scope": 'story',
        "slot": 'prologue',
        "variant": '',
        "order": 5,
        "conditional": False,
        "body": '[시작 상황]\n{prologue}',
    },
    {
        "id": uuid.UUID('7328072b-7455-483d-a144-448510154bdf'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'generation',
        "scope": 'both',
        "slot": 'history',
        "variant": '',
        "order": 6,
        "conditional": True,
        "body": '[대화 기록]\n{history_lines}',
    },
    {
        "id": uuid.UUID('96fe19dd-a343-4df0-a0ad-3ead14d20f94'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'generation',
        "scope": 'story',
        "slot": 'keyword_notes',
        "variant": '',
        "order": 7,
        "conditional": True,
        "body": '[키워드북]\n{keyword_note_lines}',
    },
    {
        "id": uuid.UUID('d943628f-085f-46f4-992b-bb11dea83c3d'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'generation',
        "scope": 'story',
        "slot": 'shortcut_prompt',
        "variant": '',
        "order": 8,
        "conditional": True,
        "body": '[단축어]\n{shortcut_prompt}',
    },
    {
        "id": uuid.UUID('ab7e50d5-cf4b-41b0-91c7-70d32b2042de'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'generation',
        "scope": 'both',
        "slot": 'final_frame',
        "variant": '',
        "order": 9,
        "conditional": False,
        "body": '{user_label}: {user_message}\n{assistant_label}:',
    },
    {
        "id": uuid.UUID('5e236909-5341-4776-aa4a-c5be3ab94161'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'stat_judgment',
        "scope": 'story',
        "slot": 'stat_defs_intro',
        "variant": '',
        "order": 1,
        "conditional": False,
        "body": '다음은 스토리 챗의 스탯 정의와 현재 값이다.\n{stat_lines}',
    },
    {
        "id": uuid.UUID('cd7be0f0-b2f9-41e1-8db5-54823edc68d4'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'stat_judgment',
        "scope": 'story',
        "slot": 'turn_context',
        "variant": '',
        "order": 2,
        "conditional": False,
        "body": '[대화 기록]\n{user_label}: {user_message}\n{assistant_label}: {assistant_message}',
    },
    {
        "id": uuid.UUID('0b153cd5-6f38-4cdb-af20-dea9f2b1cb00'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'stat_judgment',
        "scope": 'story',
        "slot": 'judgment_instruction',
        "variant": '',
        "order": 3,
        "conditional": False,
        "body": "위 대화, 특히 마지막 사용자 행동과 그에 대한 응답을 근거로 각 스탯이 이번 턴에 어떻게 변해야 하는지 판단하라. 변화가 없는 스탯은 statChanges에 포함하지 않아도 된다. newValue는 항상 그 스탯의 최종 절대값으로 응답하라. 각 스탯 설명에 적힌 증감 제약은 연출 지침이 아니라 반드시 지켜야 하는 규칙이다. '절대 늘어나지 않는다'고 적힌 스탯은 현재값보다 큰 값을 내지 말고, '절대 감소하지 않는다'고 적힌 스탯은 현재값보다 작은 값을 내지 마라.",
    },
    {
        "id": uuid.UUID('75e9d451-2fc1-43db-8f1e-9bd6ba4ace48'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'ending_judgment',
        "scope": 'story',
        "slot": 'history_header',
        "variant": '',
        "order": 1,
        "conditional": False,
        "body": '다음은 스토리 챗의 대화 기록이다.',
    },
    {
        "id": uuid.UUID('b2010945-9524-4036-9b78-890b68f4ae3c'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'ending_judgment',
        "scope": 'story',
        "slot": 'turn_context',
        "variant": '',
        "order": 2,
        "conditional": False,
        "body": '[대화 기록]\n{turn_lines}',
    },
    {
        "id": uuid.UUID('d34d8261-a580-4fe3-8242-94cf53235b60'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'ending_judgment',
        "scope": 'story',
        "slot": 'criteria',
        "variant": '',
        "order": 3,
        "conditional": False,
        "body": '아래는 하나의 엔딩이 발동하기 위한 판정 기준이다. 지금까지의 대화가 이 기준을 충족하는지 판단하라.\n[판정 기준]\n{judgment_prompt}',
    },
    {
        "id": uuid.UUID('971a1e99-e122-42fa-84aa-abdef0d31f69'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'image_judgment',
        "scope": 'character',
        "slot": 'image_list_intro',
        "variant": '',
        "order": 1,
        "conditional": False,
        "body": '다음은 이 캐릭터에 등록된 상황별 이미지 목록이다(우선순위가 높은 순서로 나열됨).\n{image_lines}',
    },
    {
        "id": uuid.UUID('e3cc453e-efe2-4dec-8c51-f178588c5676'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'image_judgment',
        "scope": 'character',
        "slot": 'turn_context',
        "variant": '',
        "order": 2,
        "conditional": False,
        "body": '[대화 기록]\n{turn_lines}',
    },
    {
        "id": uuid.UUID('a91b00f4-9d8d-4604-9e46-5cf0efc7526c'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'image_judgment',
        "scope": 'character',
        "slot": 'judgment_instruction',
        "variant": '',
        "order": 3,
        "conditional": False,
        "body": '위 대화, 특히 마지막 사용자 행동과 그에 대한 캐릭터의 응답을 근거로 이번 턴에 노출 조건이 충족된 이미지가 있는지 판단하라. 여러 이미지의 조건이 동시에 충족되면 목록에서 더 앞에 있는(우선순위가 높은) 이미지 하나만 선택하라. 조건을 충족하는 이미지가 없으면 matchedImageEntityId를 null로 응답하라.',
    },
    {
        "id": uuid.UUID('a3f24c08-753b-46af-bfd4-f39aeeec5d0f'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'publish_filter',
        "scope": 'character',
        "slot": 'intro_instruction',
        "variant": '',
        "order": 1,
        "conditional": False,
        "body": '다음은 사용자가 발행하려는 AI 캐릭터의 등록 정보다. 아래 텍스트와 함께 첨부된 이미지(대표 이미지 및 상황별 이미지가 있다면 그것들도 포함)를 모두 심사해, 선정성/폭력성/혐오 표현/불법 콘텐츠 등 서비스에 부적절한 내용이 있는지 판단하라.',
    },
    {
        "id": uuid.UUID('54251b3b-9c62-46c7-9b2f-6c5a27e8a19a'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'publish_filter',
        "scope": 'story',
        "slot": 'intro_instruction',
        "variant": '',
        "order": 1,
        "conditional": False,
        "body": '다음은 사용자가 발행하려는 스토리 콘텐츠의 등록 정보다. 아래 텍스트와 함께 첨부된 이미지(대표 이미지)를 모두 심사해, 선정성/폭력성/혐오 표현/불법 콘텐츠 등 서비스에 부적절한 내용이 있는지 판단하라.',
    },
    {
        "id": uuid.UUID('59a6901a-643a-4968-96eb-108fac984417'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'publish_filter',
        "scope": 'both',
        "slot": 'name',
        "variant": '',
        "order": 2,
        "conditional": False,
        "body": '[이름]\n{name}',
    },
    {
        "id": uuid.UUID('7d513b07-236c-482b-b8a4-840f87f392f4'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'publish_filter',
        "scope": 'both',
        "slot": 'one_liner',
        "variant": '',
        "order": 3,
        "conditional": False,
        "body": '[한줄소개]\n{one_liner}',
    },
    {
        "id": uuid.UUID('e60e98a1-e6af-4c42-a144-9e794635b088'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'publish_filter',
        "scope": 'character',
        "slot": 'intro',
        "variant": '',
        "order": 4,
        "conditional": False,
        "body": '[인트로]\n{intro}',
    },
    {
        "id": uuid.UUID('0c326757-c7aa-483f-9537-558d3c320a86'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'publish_filter',
        "scope": 'story',
        "slot": 'setting_text',
        "variant": '',
        "order": 5,
        "conditional": True,
        "body": '[세계관/설정]\n{setting_text}',
    },
    {
        "id": uuid.UUID('2db8ef1f-eb31-4a62-850e-24ce886a0e4d'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'publish_filter',
        "scope": 'story',
        "slot": 'development_example_legacy',
        "variant": '',
        "order": 6,
        "conditional": True,
        "body": '[전개 예시]\n{development_example}',
    },
    {
        "id": uuid.UUID('e113825c-d9c6-45d7-a91d-5c13f29151ce'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'publish_filter',
        "scope": 'story',
        "slot": 'custom_prompt',
        "variant": '',
        "order": 7,
        "conditional": True,
        "body": '[커스텀 프롬프트]\n{custom_prompt}',
    },
    {
        "id": uuid.UUID('9ad7ee29-edf0-4161-a1bb-a9c6377c589e'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'publish_filter',
        "scope": 'story',
        "slot": 'rules',
        "variant": '',
        "order": 8,
        "conditional": True,
        "body": '[규칙]\n{rules}',
    },
    {
        "id": uuid.UUID('b89b2e9c-6d20-496a-a276-c5e0a90dce11'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'publish_filter',
        "scope": 'story',
        "slot": 'user_goal',
        "variant": '',
        "order": 9,
        "conditional": True,
        "body": '[사용자의 역할과 목표]\n{user_goal}',
    },
    {
        "id": uuid.UUID('45ce5baa-cc89-413f-9e2d-e300a4c5e2ef'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'publish_filter',
        "scope": 'story',
        "slot": 'development_examples_pairs',
        "variant": '',
        "order": 10,
        "conditional": True,
        "body": '[전개 예시(쌍)]\n{example_lines}',
    },
    {
        "id": uuid.UUID('9b7dd843-60f0-49f0-8f44-1d09234f2432'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'publish_filter',
        "scope": 'character',
        "slot": 'example_dialogues',
        "variant": '',
        "order": 11,
        "conditional": True,
        "body": '[예시 대화]\n{dialogue_lines}',
    },
    {
        "id": uuid.UUID('10ef4f4c-f1a1-4bc0-90aa-428f5be3627c'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'publish_filter',
        "scope": 'character',
        "slot": 'character_prompt',
        "variant": '',
        "order": 12,
        "conditional": False,
        "body": '[캐릭터 프롬프트]\n{character_prompt}',
    },
    {
        "id": uuid.UUID('df8f4299-d358-4f6b-9119-a44256a2cc4b'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'publish_filter',
        "scope": 'both',
        "slot": 'detail_description',
        "variant": '',
        "order": 13,
        "conditional": False,
        "body": '[상세 설명]\n{detail_description}',
    },
    {
        "id": uuid.UUID('5ba46cf8-fad2-46e7-9603-4f5b8381ce4b'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'publish_filter',
        "scope": 'story',
        "slot": 'starting_setups',
        "variant": '',
        "order": 14,
        "conditional": True,
        "body": '[시작 설정]\n{setup_lines}',
    },
    {
        "id": uuid.UUID('773ab97b-f819-4d86-bb62-4ee8b618b26c'),
        "prompt_set_id": PROMPT_SET_ID,
        "channel": 'publish_filter',
        "scope": 'both',
        "slot": 'verdict_instruction',
        "variant": '',
        "order": 15,
        "conditional": False,
        "body": '부적절한 내용이 없으면 passed=true, reason은 null로 응답하라. 부적절한 내용이 있으면 passed=false와 함께 어떤 부분이 어떤 이유로 문제인지 reason에 한국어로 간결히 설명하라.',
    },
]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "prompt_sets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("user_label", sa.Text(), nullable=False),
        sa.Column("story_assistant_label", sa.Text(), nullable=False),
        sa.Column("story_example_label", sa.Text(), nullable=False),
        sa.Column("character_assistant_label", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_prompt_sets_draft", "prompt_sets", ["status"], unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.create_index(
        "ix_prompt_sets_published_at", "prompt_sets", [sa.literal_column("published_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_prompt_sets_version_published", "prompt_sets", ["version"], unique=True,
        postgresql_where=sa.text("status = 'published'"),
    )
    op.create_table(
        "prompt_sections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prompt_set_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("slot", sa.Text(), nullable=False),
        sa.Column("variant", sa.Text(), server_default="", nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("conditional", sa.Boolean(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["prompt_set_id"], ["prompt_sets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_prompt_sections_set_channel_order", "prompt_sections",
        ["prompt_set_id", "channel", "order"], unique=False,
    )
    op.create_index(
        "ix_prompt_sections_set_channel_scope_slot_variant", "prompt_sections",
        ["prompt_set_id", "channel", "scope", "slot", "variant"], unique=True,
    )

    published_at = datetime.now(UTC)
    op.bulk_insert(
        prompt_sets_table,
        [
            {
                "id": PROMPT_SET_ID,
                "version": "1",
                "status": "published",
                "user_label": "사용자",
                "story_assistant_label": "진행자",
                "story_example_label": "서술자",
                "character_assistant_label": "캐릭터",
                "note": "",
                "published_at": published_at,
            }
        ],
    )
    op.bulk_insert(prompt_sections_table, SEED_SECTIONS)


def downgrade() -> None:
    """Downgrade schema. 이 리비전이 만든 테이블을 통째로 지우므로(= 이 리비전이 심은
    행만 있으므로) 시드 행을 지우는 별도 DELETE는 필요 없다."""
    op.drop_index("ix_prompt_sections_set_channel_scope_slot_variant", table_name="prompt_sections")
    op.drop_index("ix_prompt_sections_set_channel_order", table_name="prompt_sections")
    op.drop_table("prompt_sections")
    op.drop_index(
        "ix_prompt_sets_version_published", table_name="prompt_sets",
        postgresql_where=sa.text("status = 'published'"),
    )
    op.drop_index("ix_prompt_sets_published_at", table_name="prompt_sets")
    op.drop_index(
        "ix_prompt_sets_draft", table_name="prompt_sets",
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.drop_table("prompt_sets")
