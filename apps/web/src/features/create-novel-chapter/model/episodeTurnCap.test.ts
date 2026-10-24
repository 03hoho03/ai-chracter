import { describe, expect, it } from "vitest";

import type { ChapterModelOption } from "@/entities/novel";

import { toNoWritableModelRefusal, toSceneOutlineTurnNote } from "./episodeTurnCap";

const CAPS = [
  { name: "Gemini", maxTurns: 45 },
  { name: "Sonnet 5.5", maxTurns: 20 },
  { name: "Opus 5.5", maxTurns: 20 },
];

// 장면 구성안을 사기 전에 알려야 한다 — 산 뒤 구성안에서 화를 나누면 그 장면 구성안은 낡아 다시 사야 한다.
describe("장면 구성안 확인 창의 턴 상한 한 줄", () => {
  it("상한 안이면 없다", () => {
    expect(toSceneOutlineTurnNote(20, CAPS)).toBeUndefined();
  });

  it("일부 모델만 넘으면 쓸 수 있는 모델과 두 길(화 나누기·장면 덜기)을 말한다", () => {
    expect(toSceneOutlineTurnNote(25, CAPS)).toBe(
      "이 화는 25턴이라 이대로는 원고를 Gemini 로만 쓸 수 있어요(Sonnet 5.5·Opus 5.5 는 20턴까지). 다른 모델로 쓰려면 먼저 구성안에서 화를 나누거나, 장면 구성안에서 장면을 덜어주세요.",
    );
  });

  it("모든 모델을 넘으면 그대로는 어느 모델로도 못 쓴다고 말한다", () => {
    expect(toSceneOutlineTurnNote(48, CAPS)).toBe(
      "이 화는 48턴이라 이대로는 어느 모델로도 원고를 쓸 수 없어요(45턴까지). 먼저 구성안에서 화를 나누거나, 장면 구성안에서 장면을 덜어주세요.",
    );
  });

  it("턴 수를 모르면 없다", () => {
    expect(toSceneOutlineTurnNote(null, CAPS)).toBeUndefined();
  });
});

describe("원고 확인 창 대신 안내 — 고를 수 있는 모델이 없을 때", () => {
  const able: ChapterModelOption = { id: "gemini", name: "Gemini", cost: 80, disabledReason: undefined };
  const unable: ChapterModelOption = { id: "opus", name: "Opus 5.5", cost: 300, disabledReason: "대화가 길어 이 모델로는 못 써요" };

  it("하나라도 고를 수 있으면 확인 창을 연다", () => {
    expect(toNoWritableModelRefusal([able, unable], 25)).toBeUndefined();
  });

  it("모두 못 쓰면 턴 수와 할 일을 말한다", () => {
    expect(toNoWritableModelRefusal([{ ...able, disabledReason: "x" }, unable], 48)).toBe(
      "이 화는 48턴이라 지금 고를 수 있는 모델로는 원고를 쓸 수 없어요. 구성안에서 화를 나누거나 장면 구성안에서 장면을 덜어주세요.",
    );
    expect(toNoWritableModelRefusal([unable], null)).toBe(
      "지금 고를 수 있는 모델로는 이 화의 원고를 쓸 수 없어요. 구성안에서 화를 나누거나 장면 구성안에서 장면을 덜어주세요.",
    );
  });

  it("목록이 비면 여기서 말하지 않는다(따로 다룬다)", () => {
    expect(toNoWritableModelRefusal([], 48)).toBeUndefined();
  });
});
