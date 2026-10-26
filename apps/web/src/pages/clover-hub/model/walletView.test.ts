import { describe, expect, it } from "vitest";

import type { MeResponse } from "@/entities/session";

import type { HubViewer } from "./hubViewer";
import { getGuestLoginLabel, getWalletView, isCheckingResolved } from "./walletView";

const MEMBER: HubViewer = { kind: "member", me: { id: "u1" } as unknown as MeResponse };
const BALANCE = { balance: 120 };

describe("getWalletView", () => {
  it("세션을 묻는 중이면 잔액이 와 있어도 대기다", () => {
    expect(getWalletView({ kind: "pending" }, { data: BALANCE, isError: false })).toEqual({ kind: "pending" });
  });

  // 비로그인에게 잔액을 물으면 401 이고, "0"을 보이면 로그인한 적 있는 사람이 잔액이 사라진 것으로 읽는다.
  it("로그인하지 않았으면 잔액 대신 로그인 안내다", () => {
    expect(getWalletView({ kind: "guest" }, { data: undefined, isError: false })).toEqual({ kind: "guest" });
  });

  it("회원이고 잔액이 아직 없으면 대기다", () => {
    expect(getWalletView(MEMBER, { data: undefined, isError: false })).toEqual({ kind: "pending" });
  });

  // 받지 못한 잔액을 0으로 그리면 충전한 사람이 잔액이 사라진 것으로 읽는다.
  it("잔액을 받지 못했으면 0이 아니라 오류다", () => {
    expect(getWalletView(MEMBER, { data: undefined, isError: true })).toEqual({ kind: "error" });
  });

  it("다시 받기만 실패했으면 이미 받은 잔액을 그대로 보인다", () => {
    expect(getWalletView(MEMBER, { data: BALANCE, isError: true })).toEqual({ kind: "ready", balance: BALANCE });
  });

  it("받은 잔액을 보인다", () => {
    expect(getWalletView(MEMBER, { data: BALANCE, isError: false })).toEqual({ kind: "ready", balance: BALANCE });
  });
});

describe("getGuestLoginLabel", () => {
  it("비로그인이 살 수 있는 갈래면 충전으로 이어진다고 말한다", () => {
    expect(getGuestLoginLabel("guest")).toBe("로그인하고 충전하기");
  });

  // 결제가 꺼져 있으면 로그인해도 충전할 수 없다 — 할 수 없는 동작을 약속하지 않는다.
  it("결제가 꺼져 있으면 충전을 약속하지 않는다", () => {
    expect(getGuestLoginLabel("disabled")).toBe("로그인하고 잔액 보기");
  });

  it("상품 응답을 아직 모르면 충전을 약속하지 않는다", () => {
    expect(getGuestLoginLabel(undefined)).toBe("로그인하고 잔액 보기");
  });
});

describe("isCheckingResolved", () => {
  // 확인 중으로 끝난 뒤 잔액이 늘었으면 웹훅이 지급한 것이다 — "확인 중"을 계속 보이면 이미 반영된 결제를 기다리게 한다.
  it("확인 중이 뜬 때보다 잔액이 늘었으면 풀렸다", () => {
    expect(isCheckingResolved({ atSettle: 100, firstArrived: undefined }, 200)).toBe(true);
  });

  // 결제창에서 돌아와 화면을 새로 열면 결과가 잔액보다 먼저 나와 그때의 잔액이 없다. 기준을 비워 두면 잔액이 늘어도
  // 영원히 "확인 중"이다 — 그 뒤 처음 도착한 잔액을 기준으로 삼는다.
  it("결과가 나온 때의 잔액이 없으면 그 뒤 처음 도착한 잔액보다 늘었는지 본다", () => {
    expect(isCheckingResolved({ atSettle: undefined, firstArrived: 100 }, 200)).toBe(true);
    expect(isCheckingResolved({ atSettle: undefined, firstArrived: 100 }, 100)).toBe(false);
  });

  it("결과가 나온 때의 잔액이 있으면 그것이 기준이다", () => {
    expect(isCheckingResolved({ atSettle: 200, firstArrived: 100 }, 150)).toBe(false);
  });

  it.each([
    [100, 100],
    [100, 50],
    [100, undefined],
  ])("늘지 않았거나 지금 잔액이 없으면 그대로다 (%s → %s)", (before, after) => {
    expect(isCheckingResolved({ atSettle: before, firstArrived: undefined }, after)).toBe(false);
  });

  it("기준이 될 잔액이 하나도 없으면 그대로다", () => {
    expect(isCheckingResolved({ atSettle: undefined, firstArrived: undefined }, 200)).toBe(false);
  });
});
