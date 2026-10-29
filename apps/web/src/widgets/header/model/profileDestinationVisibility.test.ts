import { describe, expect, it } from "vitest";

import type { EnabledFeature } from "@/entities/session";

import { isProfileDestinationVisible } from "./profileDestinationVisibility";

describe("isProfileDestinationVisible", () => {
  // 정산은 전역 스위치라 계정별 허용이 아니지만 같은 목록(`enabledFeatures`)으로 온다 — 꺼진 동안 진입점이 보이면
  // 누르자마자 "이용할 수 없어요"만 보는 화면이 된다.
  it("크리에이터 정산은 정산이 열린 계정에만 보인다", () => {
    expect(isProfileDestinationVisible("creator-payout", [])).toBe(false);
    expect(isProfileDestinationVisible("creator-payout", ["novelize"])).toBe(false);
    expect(isProfileDestinationVisible("creator-payout", ["creator_payout"])).toBe(true);
  });

  it("기능에 딸리지 않은 목적지는 허용 기능과 무관하게 보인다", () => {
    expect(isProfileDestinationVisible("chats", [])).toBe(true);
    expect(isProfileDestinationVisible("mypage", [])).toBe(true);
  });

  it("허용 기능 필드가 없는 옛 /me 응답이면 터지지 않고 기능에 딸린 목적지만 숨긴다", () => {
    const oldMe: { enabledFeatures?: EnabledFeature[] } = {};
    expect(isProfileDestinationVisible("creator-payout", oldMe.enabledFeatures)).toBe(false);
    expect(isProfileDestinationVisible("chats", oldMe.enabledFeatures)).toBe(true);
  });
});

/** 출석판은 늘 열려 있어 가격 응답의 출석 스위치를 읽지 않고 메뉴·드로어·좌측 패널에 늘 보인다. */
describe("isProfileDestinationVisible — 출석판", () => {
  it("출석판은 허용 기능과 무관하게 보인다", () => {
    expect(isProfileDestinationVisible("attendance", [])).toBe(true);
    expect(isProfileDestinationVisible("attendance", ["creator_payout"])).toBe(true);
  });

  // 비로그인 화면은 허용 기능이 없는 것으로 넘긴다 — 출석판은 비로그인도 들어와 공개 보상표를 본다.
  it("허용 기능을 모르는 비로그인 화면에서도 보인다", () => {
    expect(isProfileDestinationVisible("attendance", undefined)).toBe(true);
  });
});
