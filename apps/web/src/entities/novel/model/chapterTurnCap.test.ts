import { describe, expect, it } from "vitest";

import { toOverCapPhrase, toTurnCapFit } from "./chapterTurnCap";

const GEMINI = { name: "Gemini", maxTurns: 45 };
const SONNET = { name: "Sonnet 5.5", maxTurns: 20 };
const OPUS = { name: "Opus 5.5", maxTurns: 30 };

describe("toTurnCapFit — 화 턴 수와 원고 모델 상한", () => {
  // 상한과 같은 턴 수는 쓸 수 있다 — 서버도 상한을 "넘을 때" 거절한다.
  it("모든 상한 안이면 맞는다(상한과 같아도)", () => {
    expect(toTurnCapFit(20, [GEMINI, SONNET])).toEqual({ kind: "fits" });
  });

  it("일부만 넘으면 쓸 수 있는 모델과 넘는 모델을 상한별로 가른다(작은 상한부터)", () => {
    expect(toTurnCapFit(31, [GEMINI, SONNET, OPUS])).toEqual({
      kind: "some",
      ableNames: ["Gemini"],
      over: [
        { names: ["Sonnet 5.5"], maxTurns: 20 },
        { names: ["Opus 5.5"], maxTurns: 30 },
      ],
    });
  });

  it("모두 넘으면 가장 큰 상한을 준다", () => {
    expect(toTurnCapFit(46, [GEMINI, SONNET])).toEqual({ kind: "none", maxTurns: 45 });
  });

  it("턴 수를 모르거나 상한 목록이 비었으면 판정하지 않는다", () => {
    expect(toTurnCapFit(null, [GEMINI])).toBeUndefined();
    expect(toTurnCapFit(undefined, [GEMINI])).toBeUndefined();
    expect(toTurnCapFit(99, [])).toBeUndefined();
  });
});

describe("toOverCapPhrase", () => {
  it("같은 상한은 이름을 가운뎃점으로 묶고, 다른 상한은 쉼표로 잇는다", () => {
    expect(toOverCapPhrase([{ names: ["Sonnet 5.5", "Opus 5.5"], maxTurns: 20 }])).toBe("Sonnet 5.5·Opus 5.5 는 20턴까지");
    expect(
      toOverCapPhrase([
        { names: ["Sonnet 5.5"], maxTurns: 20 },
        { names: ["Opus 5.5"], maxTurns: 30 },
      ]),
    ).toBe("Sonnet 5.5 는 20턴, Opus 5.5 는 30턴까지");
  });
});
