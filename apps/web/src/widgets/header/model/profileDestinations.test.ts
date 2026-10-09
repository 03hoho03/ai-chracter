import { describe, expect, it } from "vitest";

import { PROFILE_MENU_DESTINATION_GROUPS, SIDE_PANEL_DESTINATION_KEYS, SIDE_PANEL_RAIL_CHATS_KEY } from "./profileDestinations";
import { isProfileDestinationVisible } from "./profileDestinationVisibility";

const MENU_KEYS = PROFILE_MENU_DESTINATION_GROUPS.flatMap((group) => group.keys);

describe("목적지 자리", () => {
  // 패널이 보이는 폭에서는 헤더의 프로필 메뉴도 함께 보이도록 짠다 — 한 키가 두 자리에 있으면 메뉴를 연 화면에 같은
  // 항목이 두 번 보인다.
  it("패널 내비·레일의 내 채팅목록·프로필 메뉴는 키가 겹치지 않는다", () => {
    const placed = [...SIDE_PANEL_DESTINATION_KEYS, SIDE_PANEL_RAIL_CHATS_KEY, ...MENU_KEYS];
    expect(new Set(placed).size).toBe(placed.length);
  });

  it("패널 내비는 홈·작품 만들기·내 작품·내 소설·이미지 생성·즐겨찾기 순서다", () => {
    expect(SIDE_PANEL_DESTINATION_KEYS).toEqual(["home", "builder", "my-works", "novels", "studio-images", "favorites"]);
  });

  it("프로필 메뉴에는 계정과 고객센터만 남고, 크리에이터 정산은 클로버 바로 뒤에 있다", () => {
    expect(PROFILE_MENU_DESTINATION_GROUPS.map((group) => group.label)).toEqual(["계정", "고객센터"]);
    expect(PROFILE_MENU_DESTINATION_GROUPS[0].keys).toEqual(["profile", "personas", "clover", "creator-payout", "mypage"]);
  });
});

describe("비로그인일 때 패널 목적지", () => {
  it("로그인이 필요한 항목은 보이고 기능에 딸린 항목(내 소설)만 숨는다", () => {
    expect(SIDE_PANEL_DESTINATION_KEYS.filter((key) => isProfileDestinationVisible(key, undefined))).toEqual([
      "home",
      "builder",
      "my-works",
      "studio-images",
      "favorites",
    ]);
    expect(isProfileDestinationVisible(SIDE_PANEL_RAIL_CHATS_KEY, undefined)).toBe(true);
  });
});
