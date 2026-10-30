import { describe, expect, it } from "vitest";

import type { AttemptDetail, TurnDetail } from "@/shared/api/client";

import { describeRaw, dumpSourceLabel, dumpSources, pickDumpRecord } from "./rawSource";

const NO_DUMP_TEXT = "이 묶음에는 프롬프트 덤프가 없어 프롬프트·지시문 원문이 없다";

function attempt(overrides: Partial<AttemptDetail> = {}): AttemptDetail {
  return {
    index: 1,
    selected: true,
    serverRejected: false,
    record: {},
    driverStatChanges: [],
    generationDump: null,
    chatTurns: [],
    ...overrides,
  };
}

function turnDetail(overrides: Partial<TurnDetail> = {}): TurnDetail {
  return {
    turn: 3,
    supplemented: false,
    replaced: false,
    attempts: [],
    earlierGenerationDumps: [],
    judgmentDumps: [],
    backgroundDumps: [],
    replacements: [],
    memorySnapshot: null,
    memorySnapshotChangedHere: false,
    metrics: null,
    mismatches: [],
    cautions: [],
    recordLimits: [],
    ...overrides,
  };
}

describe("pickDumpRecord", () => {
  const detail = turnDetail({
    earlierGenerationDumps: [{ prompt: "앞선 1" }, { prompt: "앞선 2" }],
    judgmentDumps: [{ prompt: "판정 1" }],
    backgroundDumps: [{ record: { prompt: "백그라운드 1" }, placement: "turnField" }],
  });

  it("생성은 보고 있는 시도에 붙은 생성 덤프, 나머지는 그 턴 목록의 n번째(1부터)", () => {
    const withDump = attempt({ generationDump: { prompt: "생성" } });

    expect(pickDumpRecord(detail, withDump, { kind: "generation" })).toEqual({ prompt: "생성" });
    expect(pickDumpRecord(detail, withDump, { kind: "earlier", index: 2 })).toEqual({ prompt: "앞선 2" });
    expect(pickDumpRecord(detail, withDump, { kind: "judgment", index: 1 })).toEqual({ prompt: "판정 1" });
    expect(pickDumpRecord(detail, withDump, { kind: "background", index: 1 })).toEqual({ prompt: "백그라운드 1" });
  });

  it("없는 순번·덤프 없는 시도·시도를 모름은 undefined", () => {
    expect(pickDumpRecord(detail, attempt(), { kind: "generation" })).toBeUndefined();
    expect(pickDumpRecord(detail, undefined, { kind: "generation" })).toBeUndefined();
    expect(pickDumpRecord(detail, undefined, { kind: "earlier", index: 3 })).toBeUndefined();
    expect(pickDumpRecord(detail, undefined, { kind: "background", index: 2 })).toBeUndefined();
  });
});

describe("describeRaw", () => {
  it("칸이 글이면 그 글", () => {
    const withDump = attempt({ generationDump: { prompt: "프롬프트", systemInstruction: "지시문" } });

    expect(describeRaw(turnDetail(), withDump, { kind: "generation" }, "prompt")).toEqual({ kind: "text", text: "프롬프트" });
    expect(describeRaw(turnDetail(), withDump, { kind: "generation" }, "systemInstruction")).toEqual({
      kind: "text",
      text: "지시문",
    });
  });

  it("덤프 파일이 없는 묶음이면 측정 서버의 원문 자리 문장을 그대로 — 고르지 않은 시도여도 그 까닭이 먼저다", () => {
    const limits = turnDetail({
      recordLimits: [
        { slot: "judgmentResponse", text: "판정 응답 문장" },
        { slot: "promptDump", text: NO_DUMP_TEXT },
      ],
    });

    expect(describeRaw(limits, attempt({ selected: false }), { kind: "generation" }, "prompt")).toEqual({
      kind: "noDumpFile",
      text: NO_DUMP_TEXT,
    });
  });

  it("고르지 않은 시도의 생성 덤프는 없다 — 앞선 생성 덤프 수를 함께 싣는다", () => {
    const detail = turnDetail({ earlierGenerationDumps: [{ prompt: "앞선" }] });

    expect(describeRaw(detail, attempt({ index: 2, selected: false }), { kind: "generation" }, "prompt")).toEqual({
      kind: "notSelectedAttempt",
      earlierCount: 1,
    });
  });

  it("고른 시도인데 생성 덤프가 없거나, 판정·백그라운드 순번에 줄이 없으면 이 출처에 붙은 줄이 없다", () => {
    expect(describeRaw(turnDetail(), attempt(), { kind: "generation" }, "prompt")).toEqual({ kind: "noDumpForAttempt" });
    expect(describeRaw(turnDetail(), attempt({ selected: false }), { kind: "judgment", index: 1 }, "prompt")).toEqual({
      kind: "noDumpForAttempt",
    });
  });

  it("프롬프트 칸째 없는 줄은 원문을 빼고 만든 기록이다(지시문을 물어도)", () => {
    const excluded = attempt({ generationDump: { model: "m" } });

    expect(describeRaw(turnDetail(), excluded, { kind: "generation" }, "prompt")).toEqual({ kind: "excluded" });
    expect(describeRaw(turnDetail(), excluded, { kind: "generation" }, "systemInstruction")).toEqual({ kind: "excluded" });
  });

  it("프롬프트 칸이 글이 아닌 값(null)이면 프롬프트 탭은 그 칸이 비었다고, 지시문 탭은 지시문을 보내지 않았다고", () => {
    const nullPrompt = attempt({ generationDump: { prompt: null } });

    expect(describeRaw(turnDetail(), nullPrompt, { kind: "generation" }, "prompt")).toEqual({ kind: "emptyPrompt" });
    expect(describeRaw(turnDetail(), nullPrompt, { kind: "generation" }, "systemInstruction")).toEqual({ kind: "noField" });
  });

  it("프롬프트는 있는데 지시문 칸만 없으면 그 호출이 지시문을 보내지 않은 것이다", () => {
    const promptOnly = attempt({ generationDump: { prompt: "프롬프트" } });

    expect(describeRaw(turnDetail(), promptOnly, { kind: "generation" }, "systemInstruction")).toEqual({ kind: "noField" });
  });
});

describe("dumpSourceLabel", () => {
  const detail = turnDetail({
    judgmentDumps: [{ callSite: "chat_stat_judgment" }, {}],
    backgroundDumps: [{ record: { callSite: "memory_summary" }, placement: "previousGeneration" }],
  });

  it("출처마다 이름 — 판정·백그라운드는 그 줄의 call_site, 없으면 없다고", () => {
    expect(dumpSourceLabel(detail, attempt({ index: 2 }), { kind: "generation" })).toBe("생성 · 시도 2");
    expect(dumpSourceLabel(detail, undefined, { kind: "generation" })).toBe("생성 · 시도 -");
    expect(dumpSourceLabel(detail, undefined, { kind: "earlier", index: 1 })).toBe("앞선 생성 덤프 1");
    expect(dumpSourceLabel(detail, undefined, { kind: "judgment", index: 1 })).toBe("판정 · chat_stat_judgment");
    expect(dumpSourceLabel(detail, undefined, { kind: "judgment", index: 2 })).toBe("판정 · call_site 없음");
    expect(dumpSourceLabel(detail, undefined, { kind: "background", index: 1 })).toBe("백그라운드 · memory_summary");
  });
});

describe("dumpSources", () => {
  it("생성, 앞선 생성 덤프, 판정, 백그라운드 순으로 그 턴의 줄마다 하나씩(1부터)", () => {
    const detail = turnDetail({
      earlierGenerationDumps: [{}, {}],
      judgmentDumps: [{}],
      backgroundDumps: [{ record: {}, placement: "turnField" }],
    });

    expect(dumpSources(detail)).toEqual([
      { kind: "generation" },
      { kind: "earlier", index: 1 },
      { kind: "earlier", index: 2 },
      { kind: "judgment", index: 1 },
      { kind: "background", index: 1 },
    ]);
  });

  it("덤프 줄이 없는 턴도 생성 출처 하나는 있다", () => {
    expect(dumpSources(turnDetail())).toEqual([{ kind: "generation" }]);
  });
});
