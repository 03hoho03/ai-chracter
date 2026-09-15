"""`api.images.router._style_items()` 단위 테스트 — DB 없이, private 함수를 직접 import한다.

image-style-7-goal-prompt.md IS-5(2차 인터뷰 결정 3): 이 저장소에 private 라우터 함수를
직접 import해 테스트한 선례가 없지만 여기서 도입한다. `apps/api/CLAUDE.md`가 "DB I/O가
없는 순수 함수(스탯 클램핑, 규칙 평가, 키워드 매칭)는 ORM 모델을 세션 없이 생성자로만
채워" 테스트하라고 두는 원칙과 결이 같고, 뮤테이션 테스트를 싸게 돌리기 위한 목적이 크다
(DB를 안 타는 구간은 뮤턴트당 2.5초, 타면 3분 — 같은 문서 §커버리지로 부족하다고 느껴지면
뮤테이션 테스트). HTTP 레벨 회귀는
`test_images_capabilities_gate.py::test_partial_serving_produces_exact_availability_vector_for_all_seven_styles`가
별도로 커버한다 — 이 파일은 그 회귀를 라우팅·인증·capabilities 조회 없이 더 싸게 재확인한다.
"""

from api.images.router import _style_items


def test_partial_serving_marks_exactly_the_served_styles_available() -> None:
    """IS-5: 7종 중 2종(`chapel_glass`=2번째, `watercolor`=5번째)만 서빙되면 그 둘만
    `available=True`인 벡터가 나와야 한다. 전부/전무 서빙 픽스처는 검출력이 0이다(①
    `served`를 bool로 만들어 "하나라도 서빙되면 전부 available"이 되는 버그, ② 특정
    슬롯을 하드코딩하는 버그 둘 다 그 두 픽스처에서 우연히 정답과 일치한다) —
    그래서 이 테스트와 아래 전무 케이스를 함께 둔다."""
    items = _style_items(("chapel_glass", "watercolor"))

    assert [(item.id, item.available) for item in items] == [
        ("soft_portrait", False),
        ("chapel_glass", True),
        ("royal_drama", False),
        ("sparkle_night", False),
        ("watercolor", True),
        ("pixel_art", False),
        ("deco_cute", False),
    ]


def test_no_serving_marks_every_style_unavailable() -> None:
    """서빙 집합이 빈 채로 들어와도 `available`이 전 원소에서 False로 평가되는지 —
    빈 튜플을 "전부 서빙"으로 오독하거나 특정 슬롯을 서빙 여부와 무관하게
    True로 고정하는 버그를 잡는다."""
    items = _style_items(())

    assert [item.available for item in items] == [False] * 7
