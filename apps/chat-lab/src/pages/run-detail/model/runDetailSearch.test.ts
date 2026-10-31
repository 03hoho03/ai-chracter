import { describe, expect, it } from "vitest";

import { parseRunDetailSearch, resolveAttempt, resolveDumpSource, resolveTurn } from "./runDetailSearch";

describe("parseRunDetailSearch", () => {
  it("턴·시도는 양의 정수만 받고, 라우터가 글로 넘긴 숫자도 수로 읽는다", () => {
    expect(parseRunDetailSearch({ turn: 17, attempt: "2" })).toMatchObject({ turn: 17, attempt: 2 });
    for (const bad of [0, -1, 1.5, "abc", "", null, true]) {
      expect(parseRunDetailSearch({ turn: bad }).turn).toBeUndefined();
    }
  });

  it("탭·칸 이름은 아는 것만 받는다", () => {
    expect(parseRunDetailSearch({ raw: "instruction", inspector: "metrics", pane: "inspector" })).toMatchObject({
      raw: "instruction",
      inspector: "metrics",
      pane: "inspector",
    });
    expect(parseRunDetailSearch({ raw: "diff", inspector: "costs", pane: "left" })).toEqual({});
  });

  it("원문 출처는 종류와 1부터 센 순번의 모양만 받는다", () => {
    expect(parseRunDetailSearch({ dump: "judgment-2" }).dump).toBe("judgment-2");
    expect(parseRunDetailSearch({ dump: "generation" }).dump).toBe("generation");
    for (const bad of ["judgment-0", "judgment", "earlier-x", "prompt-1", 3]) {
      expect(parseRunDetailSearch({ dump: bad }).dump).toBeUndefined();
    }
  });
});

describe("resolveTurn", () => {
  const turns = [{ turn: 1 }, { turn: 2 }, { turn: 5 }];

  it("있는 턴이면 그 턴", () => {
    expect(resolveTurn(turns, 5)).toBe(5);
  });

  it("주소에 턴이 없거나 이 런에 없는 턴이면 첫 턴", () => {
    expect(resolveTurn(turns, undefined)).toBe(1);
    expect(resolveTurn(turns, 3)).toBe(1);
  });

  it("턴이 하나도 없으면 고를 턴이 없다", () => {
    expect(resolveTurn([], 1)).toBeUndefined();
  });
});

describe("resolveAttempt", () => {
  const attempts = [
    { index: 1, selected: false },
    { index: 2, selected: true },
  ];

  it("있는 시도면 그 시도", () => {
    expect(resolveAttempt(attempts, 1)).toBe(1);
  });

  it("주소에 시도가 없거나 이 턴에 없는 시도면 DB 응답으로 고른 시도", () => {
    expect(resolveAttempt(attempts, undefined)).toBe(2);
    expect(resolveAttempt(attempts, 9)).toBe(2);
  });

  it("고른 시도가 없으면 첫 시도, 시도가 없으면 없다", () => {
    expect(resolveAttempt([{ index: 1, selected: false }], undefined)).toBe(1);
    expect(resolveAttempt([], 1)).toBeUndefined();
  });
});

describe("resolveDumpSource", () => {
  const counts = { earlier: 1, judgment: 3, background: 0 };

  it("있는 덤프 줄을 가리키면 그것", () => {
    expect(resolveDumpSource("judgment-3", counts)).toEqual({ kind: "judgment", index: 3 });
    expect(resolveDumpSource("earlier-1", counts)).toEqual({ kind: "earlier", index: 1 });
  });

  it("없거나 이 턴에 없는 줄이면 보고 있는 시도의 생성 덤프", () => {
    expect(resolveDumpSource(undefined, counts)).toEqual({ kind: "generation" });
    expect(resolveDumpSource("judgment-4", counts)).toEqual({ kind: "generation" });
    expect(resolveDumpSource("background-1", counts)).toEqual({ kind: "generation" });
  });
});
