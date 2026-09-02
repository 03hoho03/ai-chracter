"""`prune` 의 삭제 후보 선별 — 백업과 자산이 **한 버킷에 산다**는 전제 위의 안전장치다.

기존 R2 토큰이 자산 버킷(`ai-chracter-chat`) 전용이라 백업도 그 버킷의 `backup/` 아래 둔다.
그래서 이 필터가 뚫리면 사용자 콘텐츠가 지워진다 — 실패 비용이 비대칭이라 테스트로 고정한다.
"""

import pytest

from ops.backup_db import parse_listing, prune


def test_백업_파일만_고르고_시간순으로_돌려준다() -> None:
    listing = (
        "2026-09-01 03:00:01     311296 20260901T030001Z.dump\n"
        "2026-09-03 03:00:02     312320 20260903T030002Z.dump\n"
        "2026-09-02 03:00:00     311808 20260902T030000Z.dump\n"
    )
    assert parse_listing(listing) == [
        "20260901T030001Z.dump",
        "20260902T030000Z.dump",
        "20260903T030002Z.dump",
    ]


def test_하위_디렉터리_줄과_자산_키는_후보에서_빠진다() -> None:
    """`PRE assets/` 같은 줄을 이름으로 오인하면 그 프리픽스를 통째로 지우려 든다."""
    listing = (
        "                           PRE assets/\n"
        "                           PRE daily/\n"
        "2026-08-01 12:00:00     102400 assets/profile/9f3c.png\n"
        "2026-09-01 03:00:01     311296 20260901T030001Z.dump\n"
    )
    assert parse_listing(listing) == ["20260901T030001Z.dump"]


@pytest.mark.parametrize(
    "name",
    [
        "backup.dump",  # 타임스탬프 없음
        "20260901.dump",  # 시각 부분 없음
        "20260901T030001Z.dump.bak",  # 확장자 뒤에 덧붙음
        "prefix-20260901T030001Z.dump",  # 앞에 덧붙음
        "20260901T030001Z.sql",  # 다른 확장자
    ],
)
def test_형태가_어긋나면_지우지_않는다(name: str) -> None:
    assert parse_listing(f"2026-09-01 03:00:01     311296 {name}") == []


def test_슬래시로_안_끝나는_프리픽스는_거부한다() -> None:
    """`backup` 을 넘기면 `s3 ls s3://b/backup` 이 `backup*` 을 훑어 범위가 넓어진다.

    실제 삭제는 이름 필터가 한 번 더 막지만, 애초에 의도한 폴더 밖을 보지 않게 여기서 끊는다.
    네트워크 호출 전에 터지므로 이 테스트는 R2 자격증명 없이 돈다.
    """
    with pytest.raises(RuntimeError, match="'/' 로 끝나야"):
        prune("ai-chracter-chat", "backup", keep=7)
