import { describe, expect, it } from "vitest";

import { PROFILE_MENU_DESTINATION_GROUPS, SIDE_PANEL_DESTINATION_KEYS, SIDE_PANEL_RAIL_CHATS_KEY } from "./profileDestinations";
import { isProfileDestinationVisible } from "./profileDestinationVisibility";

const MENU_KEYS = PROFILE_MENU_DESTINATION_GROUPS.flatMap((group) => group.keys);

describe("목적지 자리", () => {
  // 패널이 보이는 폭에서는 헤더의 프로필 메뉴도 함께 보인다 — 한 키가 두 자리에 있으면 메뉴를 연 화면에 같은
  // 항목이 두 번 보인다.
  it("패널 내비·레일의 내 채팅목록·프로필 메뉴는 키가 겹치지 않는다", () => {
    const placed = [...SIDE_PANEL_DESTINATION_KEYS, SIDE_PANEL_RAIL_CHATS_KEY, ...MENU_KEYS];
    expect(new Set(placed).size).toBe(placed.length);
  });

  it("패널 내비는 홈·스튜디오·작품 만들기·즐겨찾기 순서다", () => {
    expect(SIDE_PANEL_DESTINATION_KEYS).toEqual(["home", "studio", "builder", "favorites"]);
  });

  it("프로필 메뉴에는 계정과 고객센터만 남고, 출석판은 클로버 바로 앞, 크리에이터 정산은 클로버 바로 뒤에 있다", () => {
    expect(PROFILE_MENU_DESTINATION_GROUPS.map((group) => group.label)).toEqual(["계정", "고객센터"]);
    expect(PROFILE_MENU_DESTINATION_GROUPS[0].keys).toEqual([
      "profile",
      "personas",
      "attendance",
      "clover",
      "creator-payout",
      "mypage",
    ]);
  });

  it("출석판은 프로필 메뉴의 계정 그룹에 한 번만 있다", () => {
    const keys: readonly string[] = MENU_KEYS;
    const accountKeys: readonly string[] = PROFILE_MENU_DESTINATION_GROUPS[0].keys;
    expect(keys.filter((key) => key === "attendance")).toHaveLength(1);
    expect(accountKeys).toContain("attendance");
  });
});

describe("비로그인일 때 패널 목적지", () => {
  it("비로그인에게도 패널 항목은 모두 보인다(누르면 로그인으로 갔다 돌아온다)", () => {
    expect(SIDE_PANEL_DESTINATION_KEYS.filter((key) => isProfileDestinationVisible(key, undefined))).toEqual([
      "home",
      "studio",
      "builder",
      "favorites",
    ]);
    expect(isProfileDestinationVisible(SIDE_PANEL_RAIL_CHATS_KEY, undefined)).toBe(true);
  });
});
