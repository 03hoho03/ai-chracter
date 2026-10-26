import { describe, expect, it } from "vitest";

import type { MeResponse } from "@/entities/session";

import type { HubViewer } from "./hubViewer";
import { getWalletView } from "./walletView";

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
