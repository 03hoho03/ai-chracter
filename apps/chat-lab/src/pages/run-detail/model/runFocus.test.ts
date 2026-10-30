import { describe, expect, it } from "vitest";

import type { RunDetail, RunMetrics } from "@/shared/api/client";

import { describeRunFocus } from "./runFocus";

type RunCost = NonNullable<RunDetail["cost"]>;

function cost(overrides: Partial<RunCost> = {}): RunCost {
  return {
    totalUsd: 0.5,
    unmatchedUsd: 0,
    unpricedCalls: 0,
    missingTokenCalls: 0,
    pricesAsOfExport: "2026-10-01",
    pricesSha256Export: "sha",
    pricesChanged: false,
    ...overrides,
  };
}

function detail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    run: {
      runId: "run",
      path: "a/chat.jsonl",
      group: null,
      format: "current",
      supported: true,
      roomId: "room",
      hasSnapshots: true,
      hasDump: true,
      hasChatTurns: true,
    },
    meta: null,
    roomStatic: null,
    turns: [],
    series: [],
    markers: [],
    statComparisons: 0,
    cost: cost(),
    unmatchedRows: [],
    mismatches: [],
    cautions: [],
    ...overrides,
  };
}

function metrics(overrides: Partial<RunMetrics> = {}): RunMetrics {
  return {
    scored: 29,
    lost: 0,
    truncated: 0,
    selfCopy: 0,
    solicit: 0,
    ignored: 0,
    sceneOpen: 0,
    labelLeak: 0,
    userTurn: 0,
    broken: 0,
    brackets: 0,
    medianLength: null,
    medianSentences: null,
    lengthNonIncreasing: null,
    turns: [],
    ...overrides,
  };
}

const MISMATCH = { kind: "turnGap", turn: 4, detail: "이 턴 번호의 턴 줄이 없다" } as const;
const CAUTION = { kind: "roomShared", detail: "방 공유" } as const;

describe("describeRunFocus", () => {
  it("아무것도 없고 지표를 받았으면 불일치·주의·플래그 모두 없다고 한 줄", () => {
    expect(describeRunFocus(detail(), metrics())).toEqual([{ tone: "quiet", text: "불일치·주의 없음 · 플래그 없음" }]);
  });

  it("지표를 아직 못 받았으면(받는 중·실패) 플래그 없음이라고 하지 않는다", () => {
    expect(describeRunFocus(detail(), undefined)).toEqual([{ tone: "quiet", text: "불일치·주의 없음" }]);
  });

  it("불일치 → 원가 빈칸·빠진 호출 → 짝 없는 기록 → 깨짐 → 나머지 플래그 → 응답 없는 턴 → 주의 순", () => {
    const lines = describeRunFocus(
      detail({
        mismatches: [MISMATCH, MISMATCH],
        cautions: [CAUTION],
        cost: cost({ unpricedCalls: 2, missingTokenCalls: 1, unmatchedUsd: 0.25 }),
        unmatchedRows: [{ assistantMessageId: null, kind: null, turnNumber: 9, costUsd: 0.25 }],
      }),
      metrics({ broken: 1, truncated: 3, selfCopy: 1, labelLeak: 2, userTurn: 1, lost: 2, solicit: 5 }),
    );

    expect(lines).toEqual([
      { tone: "warn", text: "불일치 2건 — 기록끼리 어긋난 자리가 있다." },
      { tone: "quiet", text: "단가표에 없는 모델의 호출 2건이 원가 합에서 빠졌다." },
      { tone: "quiet", text: "토큰이 기록되지 않은 호출 1건이 있다." },
      { tone: "quiet", text: "어느 시도에도 붙지 않은 턴 기록 행 1개 ($0.2500, 런 원가에 넣지 않음)." },
      { tone: "danger", text: "깨짐 1 / 표본 29턴" },
      { tone: "quiet", text: "절단 3 / 표본 29턴" },
      { tone: "quiet", text: "자기복제 1 / 표본 29턴" },
      { tone: "quiet", text: "라벨 누출 2 / 표본 29턴" },
      { tone: "quiet", text: "사용자 대사 대필 1 / 표본 29턴" },
      { tone: "quiet", text: "응답 없는 턴 2개 — 지표 표본에서 빠졌다." },
      { tone: "warn", text: "주의 1건 — 불일치로 세지 않는 참고 사항이다." },
    ]);
  });

  it("불일치와 주의는 따로 센다 — 주의를 불일치 수에 더하지 않는다", () => {
    const lines = describeRunFocus(detail({ mismatches: [MISMATCH], cautions: [CAUTION, CAUTION, CAUTION] }), metrics());

    expect(lines.map((line) => line.text)).toEqual([
      "불일치 1건 — 기록끼리 어긋난 자리가 있다.",
      "주의 3건 — 불일치로 세지 않는 참고 사항이다.",
    ]);
  });

  it("턴 기록 파일이 없으면 원가 빈칸을 말하고, 짝 없는 기록에는 원가를 붙이지 않는다", () => {
    const lines = describeRunFocus(
      detail({ cost: null, unmatchedRows: [{ assistantMessageId: null, kind: null, turnNumber: null, costUsd: 0 }] }),
      metrics(),
    );

    expect(lines).toEqual([
      { tone: "quiet", text: "턴 기록 파일이 없어 토큰·원가가 비어 있다 — 턴 기록을 내보내면 채워진다." },
      { tone: "quiet", text: "어느 시도에도 붙지 않은 턴 기록 행 1개." },
    ]);
  });

  it("지표를 못 받았으면 플래그 줄은 없고 나머지는 그대로", () => {
    expect(describeRunFocus(detail({ mismatches: [MISMATCH] }), undefined)).toEqual([
      { tone: "warn", text: "불일치 1건 — 기록끼리 어긋난 자리가 있다." },
    ]);
  });

  it("질문·청유처럼 '먼저 볼 것'에 넣지 않는 지표는 세어도 줄이 없다", () => {
    expect(describeRunFocus(detail(), metrics({ solicit: 4, sceneOpen: 2, ignored: 1, brackets: 3 }))).toEqual([
      { tone: "quiet", text: "불일치·주의 없음 · 플래그 없음" },
    ]);
  });
});
