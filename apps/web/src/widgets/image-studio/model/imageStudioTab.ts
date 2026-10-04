// 보관함은 lg 이상 좌열/미만 바텀시트로 상시 노출되고 탭이 아니다.
// "library"를 뺀다 — `?tab=library`를 가리키는 <Link>가 0건이었다(grep 재확인 완료).
// 지금 탭은 '생성' 하나다. 탭 줄과 `?tab=` 파라미터는 다른 탭을 다시 붙이기 쉽게 남겨 두지만,
// 값은 실제로 있는 탭만 둔다 — 트리거 없는 값이 여기 남으면 `?tab=transform` 같은 옛 주소로
// 들어온 사용자의 `Tabs`가 그 값을 잡아 생성 탭 본문이 숨고 중앙이 빈다. 목록에 없는 옛 값은
// 라우트 `validateSearch`가 기본값(생성)으로 접는다.
export const IMAGE_STUDIO_TABS = ["generate"] as const;
export type ImageStudioTab = (typeof IMAGE_STUDIO_TABS)[number];

export function isImageStudioTab(value: string): value is ImageStudioTab {
  return IMAGE_STUDIO_TABS.some((tab) => tab === value);
}
