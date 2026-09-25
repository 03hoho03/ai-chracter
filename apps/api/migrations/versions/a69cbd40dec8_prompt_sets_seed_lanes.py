"""prompt sets seed lanes

Revision ID: a69cbd40dec8
Revises: bcfbfd0cd960
Create Date: 2026-09-17 21:25:14.117263

프롬프트 레인 분리의 두 번째 리비전 — 현행 활성 프롬프트 세트(옛 코드가 `WHERE status='published' ORDER BY
published_at DESC LIMIT 1`로 집는 바로 그 1행) 하나를 읽어 `story`/`character`/`publish_filter`
3레인 헤더 + 섹션으로 쪼개 새로 심는다. 기존 행(활성본 포함)은 손대지 않는다 —
`lane='legacy'` 백필은 이미 앞 리비전(`bcfbfd0cd960`)의 `server_default`가 끝냈다.

**PK 58개(헤더 3 + 섹션 55)는 작성 시점에 뽑아 하드코딩한 리터럴 UUID다.** 마이그레이션
실행 시점에 `uuid.uuid4()`를 호출하지 않는다 — 환경마다 값이 달라지는 것을 막기 위해서다
(`bd258b26c34a:PROMPT_SET_ID`·`c49014ae5b62:TERMS_ID`/`PRIVACY_ID` 선례). `NEW_SECTION_IDS`의
키 `(lane, channel, scope, slot, variant)` 55개는 `admin/prompts.py:_EXPECTED_ROWS`에
`_lanes_for`를 기계적으로 적용해 뽑았다 — story 26 / character 13 / publish_filter 16.

**`system`(5행) + `generation`(2행)의 `scope='both'` 행은 story·character 두 레인에 사본으로
들어간다.** 사본은 `scope='both'`·`body`·`order`를 그대로 유지한다 — 그래야 렌더러의
`s.scope in ("both", scope)`가 무변경이고 골든 25개가 바이트 동일이다.
`publish_filter` 채널의 `scope='both'` 4행은 레인이 하나뿐이라 복제되지 않는다.

**새 헤더 3개의 `published_at`은 현행 활성본보다 엄격히 과거다(배포 창을 닫는
트릭).** 옛 코드의 `ORDER BY published_at DESC LIMIT 1`이 앞 리비전과 이 리비전 적용 후에도 여전히
`lane='legacy'`의 완전한 48행 세트를 집도록 만든다 — 코드 배포 전까지 읽기 경로의 배포 창이
0이다. `published_at`이 NULL인 published 행이 있으면(옛 코드가 이미 그 행을 활성본으로 집고
있었다는 뜻) `None - timedelta(...)`가 `TypeError`를 내어 이 마이그레이션 자체가 실패한다 —
별도 방어 코드를 넣지 않는다(의도된 동작).

새 3행의 `version`은 현행 활성본과 **같은 문자열**이다 — `(lane, version)` 부분 유니크라
충돌하지 않고, "분리 시점에 vN을 3레인으로 옮겼다"가 이력에 남는다. 라벨 4컬럼도 세 헤더에
그대로 복사한다(드리프트는 감수한 위험).

⚠️ **`lane='legacy'` UPDATE는 쓰지 않는다.** 앞 리비전의 `server_default`가 이미 모든 기존 행을
백필했다 — 쓰면 죽은 코드이고, "앞 리비전이 백필한다"는 사실을 가린다.

**드리프트 감지기 둘**: `NEW_SECTION_IDS[(lane, channel, scope, slot, variant)]`의 `KeyError`는
현행 활성본에 예상 밖 행이 있으면 터진다. `len(section_rows) != len(NEW_SECTION_IDS)`는 예상한
행이 빠져 있으면 `RuntimeError`로 시끄럽게 터진다.

**시드 삽입은 `op.bulk_insert` + 경량 `sa.table(...)`**(`bd258b26c34a`·`c49014ae5b62` 선례) —
한글 본문이 바인드 파라미터로 가므로 이스케이프가 필요 없다.

`downgrade()`는 리터럴 헤더 id 3개로 **섹션을 먼저** `prompt_set_id IN (...)`로 지우고 그다음
헤더를 지운다(`c49014ae5b62:downgrade` 선례). ⚠️ 섹션을 리터럴 섹션 id 55개로 지우지 않는다 —
그 사이 어드민이 초안을 게시해 섹션이 교체됐으면 고아 섹션이 남고 그다음 헤더 DELETE가 FK
위반으로 터진다. 테이블은 drop하지 않는다(앞 리비전 `bcfbfd0cd960` 소관).
"""
import uuid
from collections.abc import Sequence
from datetime import timedelta

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a69cbd40dec8'
down_revision: str | Sequence[str] | None = 'bcfbfd0cd960'
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

# 헤더 3개. 리터럴 UUID — 작성 시점에 uuid.uuid4()를 한 번씩 실행해 뽑았다.
NEW_SET_IDS: dict[str, uuid.UUID] = {
    "story": uuid.UUID('d0b95c63-be01-4ddf-9d7e-9d333a98eb8a'),
    "character": uuid.UUID('1d97f02d-2cd3-4389-96be-27fe67299fa1'),
    "publish_filter": uuid.UUID('67223f55-1d9d-41f4-b992-ac09e6067445'),
}

# 섹션 55개. 키는 (lane, channel, scope, slot, variant) — admin/prompts.py:_EXPECTED_ROWS에
# _lanes_for를 기계적으로 적용해 뽑은 것과 정확히 같은 집합이다(story 26 / character
# 13 / publish_filter 16).
NEW_SECTION_IDS: dict[tuple[str, str, str, str, str], uuid.UUID] = {
    ("character", "generation", "both", "final_frame", ""): uuid.UUID('61c6caa9-0c8e-4892-b363-fa13e91017e8'),
    ("character", "generation", "both", "history", ""): uuid.UUID('319b7ccc-048f-4691-a0d7-ce76a7bccf57'),
    ("character", "generation", "character", "character_prompt", ""): uuid.UUID(
        'a2af5995-9716-4084-852b-43214e05de46'
    ),
    ("character", "generation", "character", "example_dialogues", ""): uuid.UUID(
        'c88ee87b-a5cc-4f3d-92c8-4bee406e5358'
    ),
    ("character", "image_judgment", "character", "image_list_intro", ""): uuid.UUID(
        'de9a6dd4-0d8e-4d8b-b198-a4eed997289a'
    ),
    ("character", "image_judgment", "character", "judgment_instruction", ""): uuid.UUID(
        '01abbd6f-32f8-4eaa-a54c-71a995418f9b'
    ),
    ("character", "image_judgment", "character", "turn_context", ""): uuid.UUID(
        'dfb7d51c-291f-4bb1-b65f-23b7ceedef14'
    ),
    ("character", "system", "both", "priority_tail", ""): uuid.UUID('9987fbfa-9299-4f1c-bc1f-80be654798af'),
    ("character", "system", "both", "rule_open_turn", ""): uuid.UUID('68dd339c-c925-4353-bbcf-22a2c0fec25d'),
    ("character", "system", "both", "rule_rating", ""): uuid.UUID('9065be93-ef4c-49a7-9b2b-da768e94db88'),
    ("character", "system", "both", "rule_response_format", ""): uuid.UUID('6762976a-7e3a-4e33-9930-a69d65cc00cd'),
    ("character", "system", "both", "rule_user_agency", ""): uuid.UUID('7f4f5091-3fd0-4775-ae51-16f89f7f817b'),
    ("character", "system", "character", "self_definition", ""): uuid.UUID('c4b4e7ad-5a8a-4d20-9ec2-8ed348300141'),
    ("publish_filter", "publish_filter", "both", "detail_description", ""): uuid.UUID(
        '32ff4b4f-2a90-43dd-aabc-a7425e3dcc43'
    ),
    ("publish_filter", "publish_filter", "both", "name", ""): uuid.UUID('89d1057d-8b85-41af-9fbd-fbb9267be8fd'),
    ("publish_filter", "publish_filter", "both", "one_liner", ""): uuid.UUID('38754ea1-07d6-4e30-ac9a-94f28bcedd31'),
    ("publish_filter", "publish_filter", "both", "verdict_instruction", ""): uuid.UUID(
        '75b646bb-9a30-4a3d-ab03-4beacb0ef4bc'
    ),
    ("publish_filter", "publish_filter", "character", "character_prompt", ""): uuid.UUID(
        '002e9f5d-d21f-4034-be71-a1efbca2f6d0'
    ),
    ("publish_filter", "publish_filter", "character", "example_dialogues", ""): uuid.UUID(
        'd0abe8a9-dd20-4009-a019-eb92682e38d3'
    ),
    ("publish_filter", "publish_filter", "character", "intro", ""): uuid.UUID('cb39304e-5964-4239-a176-78775e424325'),
    ("publish_filter", "publish_filter", "character", "intro_instruction", ""): uuid.UUID(
        'a8e126e9-8180-4b26-be68-7f69a7642312'
    ),
    ("publish_filter", "publish_filter", "story", "custom_prompt", ""): uuid.UUID(
        'b8d68676-cefb-43dd-a76b-b1d10413a422'
    ),
    ("publish_filter", "publish_filter", "story", "development_example_legacy", ""): uuid.UUID(
        '4d493c41-1abf-4f5a-94c8-dd496798d02c'
    ),
    ("publish_filter", "publish_filter", "story", "development_examples_pairs", ""): uuid.UUID(
        '53b5d99e-fcc8-4abb-9524-affa55e50971'
    ),
    ("publish_filter", "publish_filter", "story", "intro_instruction", ""): uuid.UUID(
        'dc57818c-e834-4a9c-abf5-eda8f892f894'
    ),
    ("publish_filter", "publish_filter", "story", "rules", ""): uuid.UUID('385221a6-b255-4145-be54-d4d788ffe09a'),
    ("publish_filter", "publish_filter", "story", "setting_text", ""): uuid.UUID(
        'b3daee61-f500-4985-9abe-468c840c684c'
    ),
    ("publish_filter", "publish_filter", "story", "starting_setups", ""): uuid.UUID(
        'a341a0fb-5178-45b1-a8e9-813aaa2db708'
    ),
    ("publish_filter", "publish_filter", "story", "user_goal", ""): uuid.UUID('e3c98921-8eda-49d5-b7db-808158e2b5dc'),
    ("story", "ending_judgment", "story", "criteria", ""): uuid.UUID('045af6ea-7a34-46f5-aac2-a0143c575613'),
    ("story", "ending_judgment", "story", "history_header", ""): uuid.UUID('8217d969-9d5b-4631-904b-27f93a0f52fc'),
    ("story", "ending_judgment", "story", "turn_context", ""): uuid.UUID('f3d4d292-f252-4c0c-a332-c13d4da16f89'),
    ("story", "generation", "both", "final_frame", ""): uuid.UUID('8531cb63-8c3c-4c06-88dd-06d76cc4067b'),
    ("story", "generation", "both", "history", ""): uuid.UUID('4918cf31-51a4-406a-9500-e48b5b05aea5'),
    ("story", "generation", "story", "base_content", ""): uuid.UUID('cc296c8f-2616-4f83-8c00-bc04dd07ae0d'),
    ("story", "generation", "story", "base_content", "custom"): uuid.UUID('0f23a540-d155-4c9a-8061-a3cca7d8fff5'),
    ("story", "generation", "story", "development_examples", ""): uuid.UUID('088eee31-79a7-44f6-a99c-d3de0e0307a6'),
    ("story", "generation", "story", "keyword_notes", ""): uuid.UUID('529062f0-15c2-4c00-89b2-f3e4d69f040a'),
    ("story", "generation", "story", "prologue", ""): uuid.UUID('890dd52a-42c2-42b9-ae3a-bf1dd0c9315a'),
    ("story", "generation", "story", "rules", ""): uuid.UUID('cebf165d-af49-4e59-baf3-8df1ca5c0d7d'),
    ("story", "generation", "story", "shortcut_prompt", ""): uuid.UUID('0f534f05-1d3a-44fe-9f59-90326205117a'),
    ("story", "generation", "story", "user_goal", ""): uuid.UUID('7fb92159-bf83-4c77-abd5-b4471d84ecb6'),
    ("story", "stat_judgment", "story", "judgment_instruction", ""): uuid.UUID('ec25df54-93e0-4285-9531-0af579b64d56'),
    ("story", "stat_judgment", "story", "stat_defs_intro", ""): uuid.UUID('ba920a6b-ab3c-4740-b6d3-a6a8828dba82'),
    ("story", "stat_judgment", "story", "turn_context", ""): uuid.UUID('6ae6b3dc-2dca-429a-ae98-bff5b6270643'),
    ("story", "system", "both", "priority_tail", ""): uuid.UUID('f0317cf8-cfca-441a-b4bd-45c9752d261c'),
    ("story", "system", "both", "rule_open_turn", ""): uuid.UUID('697967da-6d5a-427e-a378-308eed78af43'),
    ("story", "system", "both", "rule_rating", ""): uuid.UUID('049dc136-79f1-48bb-933a-f58fbea5cef3'),
    ("story", "system", "both", "rule_response_format", ""): uuid.UUID('7faba7e9-ec9f-4ae2-b9da-0cc5ec432471'),
    ("story", "system", "both", "rule_user_agency", ""): uuid.UUID('1077c0c1-c963-4082-aba6-3ebfc03d65c9'),
    ("story", "system", "story", "self_definition", ""): uuid.UUID('043510a0-64c6-4590-a912-edb339329199'),
    ("story", "system", "story", "template_instruction", "basic"): uuid.UUID('0d2c2372-1ccf-43e5-aefc-fb1972f7a5e9'),
    ("story", "system", "story", "template_instruction", "custom"): uuid.UUID('7831e9ed-722a-41bb-ac4c-65db683debcd'),
    ("story", "system", "story", "template_instruction", "emotional"): uuid.UUID(
        '2a80d9e8-1cc9-4023-bbd0-86fdd943f8dd'
    ),
    ("story", "system", "story", "template_instruction", "simulation"): uuid.UUID(
        'a143c1c5-b9ea-471e-ad1b-f3051babf8a4'
    ),
}


def _lanes_for(channel: str, scope: str) -> tuple[str, ...]:
    """레인 3개(`story`/`character`/`publish_filter`)의 정의를 코드로 옮긴 것."""
    if channel == "publish_filter":
        return ("publish_filter",)
    if channel in ("stat_judgment", "ending_judgment"):
        return ("story",)
    if channel == "image_judgment":
        return ("character",)
    # system / generation — scope='both' 행만 두 레인에 사본으로 들어간다.
    if scope == "both":
        return ("story", "character")
    return (scope,)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    # 옛 코드(load_active_prompt_set)와 글자 그대로 같은 기준이다 — 이 SELECT가 고르는 행이
    # 곧 배포 창 동안 옛 코드가 계속 읽을 행이다.
    (
        source_id,
        source_version,
        source_user_label,
        source_story_assistant_label,
        source_story_example_label,
        source_character_assistant_label,
        source_note,
        source_published_at,
    ) = bind.execute(
        sa.text(
            "SELECT id, version, user_label, story_assistant_label, story_example_label,"
            " character_assistant_label, note, published_at"
            " FROM prompt_sets WHERE status = 'published'"
            " ORDER BY published_at DESC LIMIT 1"
        )
    ).one()
    rows = bind.execute(
        sa.text(
            'SELECT channel, scope, slot, variant, body, conditional, "order"'
            " FROM prompt_sections WHERE prompt_set_id = :id"
        ),
        {"id": source_id},
    ).fetchall()

    # 역순 트릭(새 헤더를 활성본보다 1초 과거로). published_at이 NULL이면 TypeError로 여기서 시끄럽게
    # 실패한다 — 별도 방어 코드를 넣지 않는다.
    new_published_at = source_published_at - timedelta(seconds=1)

    section_rows: list[dict[str, object]] = []
    for channel, scope, slot, variant, body, conditional, order in rows:
        for lane in _lanes_for(channel, scope):
            section_rows.append(
                {
                    "id": NEW_SECTION_IDS[(lane, channel, scope, slot, variant)],
                    "prompt_set_id": NEW_SET_IDS[lane],
                    "channel": channel,
                    "scope": scope,  # ⚠️ 'both'를 그대로 유지한다
                    "slot": slot,
                    "variant": variant,
                    "body": body,  # ⚠️ 바이트 그대로 — 손대지 않는다
                    "conditional": conditional,
                    "order": order,  # ⚠️ 그대로 — 골든 바이트 동일의 조건
                }
            )

    if len(section_rows) != len(NEW_SECTION_IDS):
        raise RuntimeError(
            f"현행 활성본이 예상 슬롯 집합과 다르다: {len(section_rows)}행 조립, "
            f"{len(NEW_SECTION_IDS)}행 기대"
        )

    op.bulk_insert(
        prompt_sets_table,
        [
            {
                "id": NEW_SET_IDS[lane],
                "version": source_version,
                "status": "published",
                "lane": lane,
                "user_label": source_user_label,
                "story_assistant_label": source_story_assistant_label,
                "story_example_label": source_story_example_label,
                "character_assistant_label": source_character_assistant_label,
                "note": source_note,
                "published_at": new_published_at,
            }
            for lane in ("story", "character", "publish_filter")
        ],
    )
    op.bulk_insert(prompt_sections_table, section_rows)


def downgrade() -> None:
    """Downgrade schema. 섹션을 먼저(FK), 그다음 헤더 — 둘 다 리터럴 헤더 id로 지운다.
    섹션을 리터럴 섹션 id로 지우지 않는다(그 사이 섹션이 교체됐으면 고아가 남는다)."""
    ids = list(NEW_SET_IDS.values())
    op.execute(sa.delete(prompt_sections_table).where(prompt_sections_table.c.prompt_set_id.in_(ids)))
    op.execute(sa.delete(prompt_sets_table).where(prompt_sets_table.c.id.in_(ids)))
