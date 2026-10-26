import { describe, expect, it } from "vitest";

import type { MeResponse } from "@/entities/session";

import { toHubViewer } from "./hubViewer";

const ME = { id: "u1" } as unknown as MeResponse;

describe("toHubViewer", () => {
  // 대기를 비로그인으로 접으면 로그인한 사람에게도 첫 프레임에 로그인 안내가 그려진다.
  it("세션을 묻는 중이면 대기다", () => {
    expect(toHubViewer({ data: undefined, isPending: true })).toEqual({ kind: "pending" });
  });

  it("물었는데 세션이 없으면 비로그인이다", () => {
    expect(toHubViewer({ data: undefined, isPending: false })).toEqual({ kind: "guest" });
  });

  it("세션이 있으면 회원이다", () => {
    expect(toHubViewer({ data: ME, isPending: false })).toEqual({ kind: "member", me: ME });
  });
});
