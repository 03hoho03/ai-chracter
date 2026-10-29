import type { CloverPricingResponse } from "@/entities/clover";
import type { EnabledFeature } from "@/entities/session";

import type { ProfileDestinationKey } from "./profileDestinations";

/** 계정별로 열리는 기능에 딸린 목적지. 여기 없는 목적지는 로그인한 누구에게나 보인다. */
const REQUIRED_FEATURE: Partial<Record<ProfileDestinationKey, EnabledFeature>> = {
  "creator-payout": "creator_payout",
};

/** 운영 전체에 걸린 스위치로 열리는 목적지. 이 스위치는 계정별 허용이 아니라 전역이라 `/me` 가 아니라 공개 가격 응답에서
 * 온다. */
export type PublicSwitches = { attendance: boolean };

const REQUIRED_PUBLIC_SWITCH: Partial<Record<ProfileDestinationKey, keyof PublicSwitches>> = {
  attendance: "attendance",
};

/** 가격 응답에서 공개 스위치를 꺼낸다. 아직 못 받았거나 실패했으면 undefined. */
export function toPublicSwitches(pricing: CloverPricingResponse | undefined): PublicSwitches | undefined {
  // 생성 타입은 `attendance` 를 필수로 적지만, 웹과 API 는 따로 배포돼 출석판 이전 API 로 되돌리면 이 필드가 빠진 응답이 온다 —
  // 그때는 꺼진 것으로 본다.
  return pricing === undefined ? undefined : { attendance: pricing.attendance?.enabled ?? false };
}

/** 프로필 메뉴·모바일 드로어·좌측 패널이 목적지 배열을 그리기 전에 함께 부르는 판정이다. 숨김은 항목을
 * 그리지 않는 것으로 한다 — 링크 컴포넌트가 빈 값을 돌려주게 하면 메뉴 항목 껍데기(`DropdownMenuItem asChild`)가
 * 내용 없이 남는다.
 *
 * 비로그인 화면(좌측 패널, 드로어의 패널 목록)은 허용 기능이 없는 것(`undefined`)으로 넘겨 같은 판정을 쓴다. 그러면
 * 기능에 딸린 목적지만 숨고, 로그인이 필요한 나머지 목적지는 보인다 — 누르면 그 라우트의 `requireSession` 이 로그인으로 보냈다가 돌려보낸다.
 *
 * 허용 기능이 없으면(`undefined`) 빈 목록으로 본다. 웹과 API 는 따로 배포돼 어느 쪽이 먼저 끝날지 보장되지 않아,
 * 그 사이(또는 API 만 되돌린 동안) 이 필드가 없는 옛 `/me` 응답이 올 수 있다 — 생성 타입은 새 API 기준이라
 * 필수로 적혀 있어도 그렇다. 그때 메뉴가 통째로 터지는 대신 기능에 딸린 목적지만 숨긴다.
 *
 * 공개 스위치(`publicSwitches`)는 가격 응답을 아직 못 받았거나 실패했으면 `undefined` 이고, 그때 스위치에 딸린 목적지는
 * 숨긴다 — 꺼진 동안 화면이 바뀌지 않는 것이 먼저이고, 주소로 들어온 사람은 그 페이지가 서버 응답으로 정한다. 이 인자를
 * 필수로 두는 이유: 호출부 하나가 빠뜨리면 그 자리에서만 목적지가 조용히 숨는데, 타입이 그것을 막는다. */
export function isProfileDestinationVisible(
  key: ProfileDestinationKey,
  enabledFeatures: readonly EnabledFeature[] | undefined,
  publicSwitches: PublicSwitches | undefined,
): boolean {
  const feature = REQUIRED_FEATURE[key];
  if (feature !== undefined && !(enabledFeatures ?? []).includes(feature)) return false;
  const publicSwitch = REQUIRED_PUBLIC_SWITCH[key];
  return publicSwitch === undefined || publicSwitches?.[publicSwitch] === true;
}
