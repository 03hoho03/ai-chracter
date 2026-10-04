import { describe, expect, it } from "vitest";

import { resolveSearchInputSync } from "./searchInputSync";

describe("resolveSearchInputSync", () => {
  it("URL 검색어가 디바운스가 마지막으로 쓴 값이면 건드리지 않는다 — 그사이 친 글자를 지우지 않는다", () => {
    // `ab`를 쓴 뒤 커밋 전에 `c`를 더 친 상태에서 `ab`가 커밋돼 돌아온 경우.
    expect(
      resolveSearchInputSync({ urlQuery: "ab", lastWrittenQuery: "ab", inputValue: "abc", isExpanded: true }),
    ).toEqual({ kind: "keep" });
    // 직접 다 지워 검색어가 빠진 경우도 자기 쓰기다.
    expect(
      resolveSearchInputSync({ urlQuery: undefined, lastWrittenQuery: undefined, inputValue: "", isExpanded: true }),
    ).toEqual({ kind: "keep" });
  });

  it("바깥에서 검색어가 지워지면 펼친 입력칸을 접는다(로고·칩 ×·필터 지우기)", () => {
    expect(
      resolveSearchInputSync({ urlQuery: undefined, lastWrittenQuery: "abc", inputValue: "abc", isExpanded: true }),
    ).toEqual({ kind: "collapse" });
  });

  it("바깥에서 검색어가 다른 값으로 바뀌면 입력칸을 그 값으로 맞춘다(뒤로/앞으로)", () => {
    expect(
      resolveSearchInputSync({ urlQuery: "ab", lastWrittenQuery: "abc", inputValue: "abc", isExpanded: true }),
    ).toEqual({ kind: "fill", value: "ab" });
    // 입력을 다 지운 뒤 뒤로 가서 검색어가 되살아난 경우.
    expect(
      resolveSearchInputSync({ urlQuery: "abc", lastWrittenQuery: undefined, inputValue: "", isExpanded: true }),
    ).toEqual({ kind: "fill", value: "abc" });
  });

  it("이미 같은 말이면 다시 채우지 않는다", () => {
    expect(
      resolveSearchInputSync({ urlQuery: "ab", lastWrittenQuery: "abc", inputValue: " ab ", isExpanded: true }),
    ).toEqual({ kind: "keep" });
  });

  it("접혀 있으면 아무것도 하지 않는다 — 걸린 검색어는 칩이 보이고, 펼칠 때 그 값으로 채운다", () => {
    expect(
      resolveSearchInputSync({ urlQuery: "ab", lastWrittenQuery: "abc", inputValue: "", isExpanded: false }),
    ).toEqual({ kind: "keep" });
    expect(
      resolveSearchInputSync({ urlQuery: undefined, lastWrittenQuery: "abc", inputValue: "", isExpanded: false }),
    ).toEqual({ kind: "keep" });
  });

  it("바깥에서 지워졌어도 입력칸이 이미 비어 있으면 접지 않는다", () => {
    expect(
      resolveSearchInputSync({ urlQuery: undefined, lastWrittenQuery: "abc", inputValue: "  ", isExpanded: true }),
    ).toEqual({ kind: "keep" });
  });
});
