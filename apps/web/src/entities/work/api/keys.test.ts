import { describe, expect, it } from "vitest";

import type { MyWorksParams } from "../model/workItem";
import { workKeys } from "./keys";

const BASE: MyWorksParams = { type: "all", status: "all", q: undefined };

describe("workKeys.list", () => {
  it("같은 조건이라도 묶음이 다르면 다른 목록이다", () => {
    expect(workKeys.list({ ...BASE, bundleId: "b1" })).not.toEqual(workKeys.list({ ...BASE, bundleId: "b2" }));
    expect(workKeys.list({ ...BASE, bundleId: "b1" })).not.toEqual(workKeys.list(BASE));
  });

  it("묶음을 바꾸면 검색어 앞 칸이 달라진다 — 검색어만 바뀐 목록으로 읽혀 앞 묶음 목록이 자리표시로 남지 않게", () => {
    const first = workKeys.list({ ...BASE, bundleId: "b1", q: "밤" });
    const second = workKeys.list({ ...BASE, bundleId: "b2", q: "밤" });
    expect(first.slice(0, -1)).not.toEqual(second.slice(0, -1));
    expect(first.at(-1)).toBe("밤");
  });

  it("검색어만 다르면 마지막 칸만 다르다", () => {
    const first = workKeys.list({ ...BASE, bundleId: "b1", q: "밤" });
    const second = workKeys.list({ ...BASE, bundleId: "b1", q: "낮" });
    expect(first.slice(0, -1)).toEqual(second.slice(0, -1));
  });

  it("모든 조건 목록은 통합 목록 접두 아래에 있다 — 지우기·넣기 뒤 접두 하나로 함께 다시 받는다", () => {
    expect(workKeys.list({ ...BASE, bundleId: "b1" }).slice(0, 2)).toEqual(workKeys.lists());
  });
});
