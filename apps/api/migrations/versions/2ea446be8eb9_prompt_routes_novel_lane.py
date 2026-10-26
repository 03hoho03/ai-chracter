"""prompt routes novel lane

Revision ID: 2ea446be8eb9
Revises: e4df46a80bfa
Create Date: 2026-10-27 12:00:00.000000

모델 배정 표를 소설 레인까지 넓힌다. 데이터는 바꾸지 않는다(이 리비전은 소설 행을 넣지 않는다).

- `prompt_routes` 의 행 모양 CHECK 둘을 같은 이름으로 DROP → ADD 해 생성 단계에 소설 생성 세 단계(`novel_chapter`·
  `novel_outline`·`novel_episode_outline`)를 더한다. 소설 생성 행은 채팅 생성 행처럼 체인을 두지 않고(늘 작업 모델의 체인을
  읽는다), 호출 모델이 작업 모델(`room_model` 칸)과 같다 — 소설 차감이 작업 모델 단가라서, 다른 모델을 부르면 값과 원가가
  어긋난다. 소설 구조화 단계(문단 수정·여러 문단 수정·재검사·경계 제안)는 판정 행처럼 체인을 반드시 둔다.
- `prompt_route_revisions.lanes`(JSONB, NULL 허용, 서버 기본값 없음): 그 저장이 어느 경로의 저장인지. NULL 은 표 전체를 갈아
  끼운 옛 저장이거나 채팅 두 레인을 바꾸는 기존 경로의 저장이고, `["novel"]` 은 소설 레인 경로의 저장이다. 스냅샷(`rows`)은
  어느 경로든 저장한 뒤의 표 전체다.

**옛 이미지가 이 스키마 위에서 도는 구간**(배포 겹침, 이미지만 되돌린 동안): 옛 이미지가 쓰는 행(채팅 생성 행은 체인 없음, 판정
행은 체인 있음)은 넓힌 CHECK 를 그대로 만족한다. 옛 매퍼는 `lanes` 칸을 몰라 INSERT 에서 빠지고, NULL 허용이라 그대로 들어가
NULL(= 옛 저장)이 된다. 옛 이미지의 모델 메타데이터에 적힌 CHECK 문장은 DB 와 다르지만 런타임은 그 문장을 비교하지 않는다.

첫 문장은 `SET LOCAL lock_timeout = '5s'` 다 — CHECK 를 다시 거는 `ALTER` 는 `prompt_routes` 에, 칸을 더하는 `ALTER` 는 이력
표에 가장 강한 잠금을 잡는다. 오래 걸린 트랜잭션 뒤에서 그 잠금을 기다리는 동안 두 표를 읽는 요청(채팅 턴의 배정 캐시 미스,
어드민 배정 화면)을 줄 세우지 않게, 5초 안에 못 잡으면 실패시킨다(다시 돌리면 된다).

**downgrade**: 다시 좁히는 CHECK 는 체인 없는 소설 생성 행을 받지 않는다. 그런 행이 있으면 아무것도 바꾸기 전에 `RuntimeError`
로 멈춘다 — 어드민이 저장한 소설 행을 조용히 지우지 않는다. 새 이미지에서 소설 레인을 비워 저장한 뒤 내린다. 소설 구조화 행은
체인이 있어 좁힌 CHECK 를 만족하므로 남는다(옛 이미지는 모르는 레인의 행을 읽을 때 버린다). `lanes` 칸은 지운다 — 어느 경로의
저장이었는지는 사라지지만 스냅샷은 그대로 표 전체라, 옛 이미지의 되돌리기는 그 스냅샷을 옛 규칙(표 전체)으로 다룬다.

이 파일은 `api.*` 를 import 하지 않는다(저장소 관례).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2ea446be8eb9"
down_revision: str | Sequence[str] | None = "e4df46a80bfa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HAS_NO_CHAIN = "ck_prompt_routes_generation_has_no_chain"
_CALLS_ROOM_MODEL = "ck_prompt_routes_generation_calls_room_model"
_GENERATION_STAGES = "('chat_generate', 'novel_chapter', 'novel_outline', 'novel_episode_outline')"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint(_HAS_NO_CHAIN, "prompt_routes", type_="check")
    op.drop_constraint(_CALLS_ROOM_MODEL, "prompt_routes", type_="check")
    op.create_check_constraint(
        _HAS_NO_CHAIN, "prompt_routes", f"(stage IN {_GENERATION_STAGES}) = (chain_model IS NULL)"
    )
    op.create_check_constraint(
        _CALLS_ROOM_MODEL, "prompt_routes", f"stage NOT IN {_GENERATION_STAGES} OR call_model = room_model"
    )
    op.add_column("prompt_route_revisions", sa.Column("lanes", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    novel_generation = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM prompt_routes"
                " WHERE stage IN ('novel_chapter', 'novel_outline', 'novel_episode_outline')"
            )
        )
        .scalar_one()
    )
    if novel_generation:
        raise RuntimeError(
            f"소설 생성 배정 행 {novel_generation}개가 남아 있다 — 좁히는 CHECK 가 받지 않는 행이라 지우지 않고 멈춘다. 새 이미지에서"
            " 소설 레인을 비워 저장한 뒤 내린다."
        )
    op.drop_column("prompt_route_revisions", "lanes")
    op.drop_constraint(_HAS_NO_CHAIN, "prompt_routes", type_="check")
    op.drop_constraint(_CALLS_ROOM_MODEL, "prompt_routes", type_="check")
    op.create_check_constraint(_HAS_NO_CHAIN, "prompt_routes", "(stage = 'chat_generate') = (chain_model IS NULL)")
    op.create_check_constraint(
        _CALLS_ROOM_MODEL, "prompt_routes", "stage <> 'chat_generate' OR call_model = room_model"
    )
