import { describe, expect, it } from "vitest";

import { hasField, readBoolean, readNumber, readRecord, readRecords, readText } from "./recordFields";

describe("readText", () => {
  it("글이면 그 글(빈 글 포함), 다른 타입·없는 칸·없는 기록은 undefined", () => {
    expect(readText({ name: "호감" }, "name")).toBe("호감");
    expect(readText({ name: "" }, "name")).toBe("");
    expect(readText({ name: 3 }, "name")).toBeUndefined();
    expect(readText({}, "name")).toBeUndefined();
    expect(readText(null, "name")).toBeUndefined();
    expect(readText(undefined, "name")).toBeUndefined();
  });
});

describe("readNumber", () => {
  it("유한한 수만 — 글로 적힌 수·NaN·무한대는 undefined", () => {
    expect(readNumber({ rank: 0 }, "rank")).toBe(0);
    expect(readNumber({ rank: -1.5 }, "rank")).toBe(-1.5);
    expect(readNumber({ rank: "3" }, "rank")).toBeUndefined();
    expect(readNumber({ rank: Number.NaN }, "rank")).toBeUndefined();
    expect(readNumber({ rank: Number.POSITIVE_INFINITY }, "rank")).toBeUndefined();
    expect(readNumber(null, "rank")).toBeUndefined();
  });
});

describe("readBoolean", () => {
  it("참·거짓만 — 0·1·'true' 는 undefined", () => {
    expect(readBoolean({ done: true }, "done")).toBe(true);
    expect(readBoolean({ done: false }, "done")).toBe(false);
    expect(readBoolean({ done: 1 }, "done")).toBeUndefined();
    expect(readBoolean({ done: "true" }, "done")).toBeUndefined();
    expect(readBoolean(undefined, "done")).toBeUndefined();
  });
});

describe("readRecords", () => {
  it("목록이면 객체인 원소만 순서대로 — null·배열·글 원소는 버린다", () => {
    const first = { rank: 1 };
    const second = { rank: 2 };

    expect(readRecords({ recall: [first, null, [1], "x", second] }, "recall")).toEqual([first, second]);
  });

  it("목록이 아니면 빈 목록", () => {
    expect(readRecords({ recall: { rank: 1 } }, "recall")).toEqual([]);
    expect(readRecords({}, "recall")).toEqual([]);
    expect(readRecords(null, "recall")).toEqual([]);
  });
});

describe("readRecord", () => {
  it("객체면 그 객체, null·배열·글은 undefined", () => {
    expect(readRecord({ skipped: { reason: "끔" } }, "skipped")).toEqual({ reason: "끔" });
    expect(readRecord({ skipped: null }, "skipped")).toBeUndefined();
    expect(readRecord({ skipped: [] }, "skipped")).toBeUndefined();
    expect(readRecord({ skipped: "끔" }, "skipped")).toBeUndefined();
    expect(readRecord(undefined, "skipped")).toBeUndefined();
  });
});

describe("hasField", () => {
  it("칸이 있으면 값이 null·undefined 여도 참 — 원문을 빼고 내보낸 기록은 칸째 없다", () => {
    expect(hasField({ prompt: null }, "prompt")).toBe(true);
    expect(hasField({ prompt: undefined }, "prompt")).toBe(true);
    expect(hasField({}, "prompt")).toBe(false);
  });

  it("기록이 없거나, 물려받은 칸(toString 등)은 거짓", () => {
    expect(hasField(null, "prompt")).toBe(false);
    expect(hasField(undefined, "prompt")).toBe(false);
    expect(hasField({}, "toString")).toBe(false);
  });
});
