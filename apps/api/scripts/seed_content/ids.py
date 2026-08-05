"""시드 행의 결정적 UUID 파생.

`apps/api/CLAUDE.md` 의 "시드 행은 하드코딩 리터럴 UUID" 관례에서 의도적으로 이탈한다 —
콘텐츠 30개에 필요한 UUID 가 400개를 넘어 손으로 못 쓴다(PRD §8). 대신 리터럴 네임스페이스
하나만 두고 그 아래에서 uuid5 로 파생한다: 같은 인자면 어느 머신에서 언제 돌려도 같은
UUID 라, 재시드가 새 행을 만드는 대신 기존 행을 그대로 덮어쓴다.

버전 UUID 가 고정이라는 게 특히 중요하다 — `chat_rooms.content_version_id` 는 방 생성
시점 버전에 핀으로 고정되므로, 재시드가 새 버전을 만들면 기존 대화방이 고아가 된다.
"""

import uuid

# 실사용자 UUID 와 겹치지 않도록 seed_dev.py 의 고정 UUID 들과 같은 5eed 프리픽스를 쓴다.
# 이 값을 바꾸면 시드된 콘텐츠 전체가 새 UUID 로 다시 생기므로 절대 바꾸지 않는다.
SEED_NAMESPACE = uuid.UUID("5eed0000-0000-4000-8000-00000000f00d")

# 시드 콘텐츠 전체의 작가이자 시드 자산의 소유자. seed_dev.py 가 이 계정을 만들고
# (`USER_ID`), 기존 '미아' 캐릭터의 creator_user_id 도 이 값이라 절대 바꾸지 않는다.
SEED_AUTHOR_USER_ID = uuid.UUID("5eed0000-0000-4000-8000-000000000001")


def seed_uuid(*parts: str) -> uuid.UUID:
    """`seed_uuid("story", "romance-3rdloop", "version")` 처럼 경로를 넘겨 UUID 를 얻는다.

    파트는 `:` 로 이어 붙이므로 `seed_uuid("story", slug)` 와 `seed_uuid(f"story:{slug}")`
    는 같은 값이다.
    """
    return uuid.uuid5(SEED_NAMESPACE, ":".join(parts))
