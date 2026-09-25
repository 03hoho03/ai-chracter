// 보관함은 lg 이상 좌열/미만 바텀시트로 상시 노출되고 탭이 아니다.
// "library"를 뺀다 — `?tab=library`를 가리키는 <Link>가 0건이었다(grep 재확인 완료).
// 뒤 둘(변형/인페인트)은 아직 disabled라 값만 먼저 채운다.
export const IMAGE_STUDIO_TABS = ["generate", "transform", "inpaint"] as const;
export type ImageStudioTab = (typeof IMAGE_STUDIO_TABS)[number];

export function isImageStudioTab(value: string): value is ImageStudioTab {
  return IMAGE_STUDIO_TABS.some((tab) => tab === value);
}
