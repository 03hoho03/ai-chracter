import type { EnabledFeature } from "@/entities/session";

import type { ProfileDestinationKey } from "./profileDestinations";

/** 계정별로 열리는 기능에 딸린 목적지. 여기 없는 목적지는 로그인한 누구에게나 보인다. */
const REQUIRED_FEATURE: Partial<Record<ProfileDestinationKey, EnabledFeature>> = {
  novels: "novelize",
  "creator-payout": "creator_payout",
};

/** 프로필 메뉴·모바일 드로어·좌측 패널이 목적지 배열을 그리기 전에 함께 부르도록 둔 판정이다. 숨김은 항목을
 * 그리지 않는 것으로 한다 — 링크 컴포넌트가 빈 값을 돌려주게 하면 메뉴 항목 껍데기(`DropdownMenuItem asChild`)가
 * 내용 없이 남는다.
 *
 * 비로그인 화면도 허용 기능이 없는 것(`undefined`)으로 넘기면 같은 판정을 쓸 수 있다. 그러면 기능에 딸린 목적지만
 * 숨고, 로그인이 필요한 나머지 목적지는 보인다 — 누르면 그 라우트의 `requireSession` 이 로그인으로 보냈다가 돌려보낸다.
 *
 * 허용 기능이 없으면(`undefined`) 빈 목록으로 본다. 웹과 API 는 따로 배포돼 어느 쪽이 먼저 끝날지 보장되지 않아,
 * 그 사이(또는 API 만 되돌린 동안) 이 필드가 없는 옛 `/me` 응답이 올 수 있다 — 생성 타입은 새 API 기준이라
 * 필수로 적혀 있어도 그렇다. 그때 메뉴가 통째로 터지는 대신 기능에 딸린 목적지만 숨긴다. */
export function isProfileDestinationVisible(
  key: ProfileDestinationKey,
  enabledFeatures: readonly EnabledFeature[] | undefined,
): boolean {
  const feature = REQUIRED_FEATURE[key];
  return feature === undefined || (enabledFeatures ?? []).includes(feature);
}
