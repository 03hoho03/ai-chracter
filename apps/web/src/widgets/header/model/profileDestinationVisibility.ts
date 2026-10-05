import type { EnabledFeature } from "@/entities/session";

import type { ProfileDestinationKey } from "../ui/ProfileDestinationLink";

/** 계정별로 열리는 기능에 딸린 목적지. 여기 없는 목적지는 로그인한 누구에게나 보인다. */
const REQUIRED_FEATURE: Partial<Record<ProfileDestinationKey, EnabledFeature>> = {
  novels: "novelize",
};

/** 프로필 메뉴와 모바일 드로어가 목적지 배열을 그리기 전에 함께 부른다. 숨김은 항목을 그리지 않는 것으로
 * 한다 — 링크 컴포넌트가 빈 값을 돌려주게 하면 메뉴 항목 껍데기(`DropdownMenuItem asChild`)가 내용 없이 남는다. */
export function isProfileDestinationVisible(key: ProfileDestinationKey, enabledFeatures: readonly EnabledFeature[]): boolean {
  const feature = REQUIRED_FEATURE[key];
  return feature === undefined || enabledFeatures.includes(feature);
}
