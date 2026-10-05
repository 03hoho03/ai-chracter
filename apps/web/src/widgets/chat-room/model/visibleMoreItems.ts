import type { EnabledFeature } from "@/entities/session";

/** 계정별로 열리는 기능에 딸린 항목만 `requiredFeature` 를 가진다. 없으면 누구에게나 보인다.
 *
 * 숨김은 이 필드로만 정한다. `isActive: false` 는 "준비 중" 표지를 단 채 보여 주는 상태라 숨김과 뜻이 다르다. */
export type FeatureGatedItem = {
  requiredFeature?: EnabledFeature;
};

/** 채팅 더보기 목록에서 이 계정에 보일 항목만 남긴다. 순서는 그대로다. 데스크톱 사이드바와 모바일 시트가 같은
 * 목록 컴포넌트를 그리므로 걸러 내는 자리도 여기 하나다. */
export function visibleMoreItems<T extends FeatureGatedItem>(items: readonly T[], enabledFeatures: readonly EnabledFeature[]): T[] {
  return items.filter((item) => item.requiredFeature === undefined || enabledFeatures.includes(item.requiredFeature));
}
