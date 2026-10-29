import { describe, expect, it } from "vitest";

import type { EnabledFeature } from "@/entities/session";

import { isProfileDestinationVisible } from "./profileDestinationVisibility";

describe("isProfileDestinationVisible", () => {
  // 정산은 전역 스위치라 계정별 허용이 아니지만 같은 목록(`enabledFeatures`)으로 온다 — 꺼진 동안 진입점이 보이면
  // 누르자마자 "이용할 수 없어요"만 보는 화면이 된다.
  it("크리에이터 정산은 정산이 열린 계정에만 보인다", () => {
    expect(isProfileDestinationVisible("creator-payout", [], undefined)).toBe(false);
    expect(isProfileDestinationVisible("creator-payout", ["novelize"], undefined)).toBe(false);
    expect(isProfileDestinationVisible("creator-payout", ["creator_payout"], undefined)).toBe(true);
  });

  it("기능에 딸리지 않은 목적지는 허용 기능과 무관하게 보인다", () => {
    expect(isProfileDestinationVisible("chats", [], undefined)).toBe(true);
    expect(isProfileDestinationVisible("mypage", [], undefined)).toBe(true);
  });

  it("허용 기능 필드가 없는 옛 /me 응답이면 터지지 않고 기능에 딸린 목적지만 숨긴다", () => {
    const oldMe: { enabledFeatures?: EnabledFeature[] } = {};
    expect(isProfileDestinationVisible("creator-payout", oldMe.enabledFeatures, undefined)).toBe(false);
    expect(isProfileDestinationVisible("chats", oldMe.enabledFeatures, undefined)).toBe(true);
  });
});

/** 출석 스위치는 계정별 허용이 아니라 전역 스위치라 `/me` 가 아니라 공개 가격 응답에서 온다. */
describe("isProfileDestinationVisible — 공개 스위치", () => {
  it("출석판은 출석 스위치가 켜져 있을 때만 보인다", () => {
    expect(isProfileDestinationVisible("attendance", [], { attendance: true })).toBe(true);
    expect(isProfileDestinationVisible("attendance", [], { attendance: false })).toBe(false);
  });

  // 꺼진 동안 화면이 바뀌지 않는 것이 먼저다 — 주소로 들어온 사람은 페이지가 판 응답으로 정한다.
  it("가격 응답을 아직 못 받았거나 실패했으면 출석판을 숨긴다", () => {
    expect(isProfileDestinationVisible("attendance", ["creator_payout"], undefined)).toBe(false);
  });

  it("다른 목적지는 공개 스위치와 무관하다", () => {
    for (const publicSwitches of [undefined, { attendance: false }, { attendance: true }]) {
      expect(isProfileDestinationVisible("clover", [], publicSwitches)).toBe(true);
      expect(isProfileDestinationVisible("chats", [], publicSwitches)).toBe(true);
      expect(isProfileDestinationVisible("creator-payout", [], publicSwitches)).toBe(false);
      expect(isProfileDestinationVisible("creator-payout", ["creator_payout"], publicSwitches)).toBe(true);
    }
  });
});
