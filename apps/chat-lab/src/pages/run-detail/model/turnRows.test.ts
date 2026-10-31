import { describe, expect, it } from "vitest";

import type { AttemptDetail, DriverStatChange, ReplyFlagsView, StatSeries, TurnSummary } from "@/shared/api/client";

import { attemptDeltas, buildTurnRows, formatStatDelta, seriesTones, type StatDelta } from "./turnRows";

function summary(overrides: Partial<TurnSummary> = {}): TurnSummary {
  return {
    turn: 1,
    attemptCount: 1,
    supplemented: false,
    replaced: false,
    lost: false,
    userText: "문을 두드린다.",
    shortcut: null,
    replyHead: "응답",
    replyLength: 2,
    driverStatChanges: [],
    recordedStatChanges: [],
    ending: null,
    failure: null,
    earlierGenerationDumps: 0,
    judgmentDumps: 0,
    backgroundDumps: 0,
    flags: null,
    statsStartKnown: true,
    statsContinueFromPrevious: true,
    costUsd: null,
    costIsLowerBound: false,
    mismatchCount: 0,
    ...overrides,
  };
}

function series(name: string, overrides: Partial<StatSeries> = {}): StatSeries {
  return { id: `id-${name}`, name, hidden: false, source: "driver", points: [], ...overrides };
}

function flags(overrides: Partial<ReplyFlagsView> = {}): ReplyFlagsView {
  return {
    length: 10,
    sentenceCount: 1,
    statusBlockLength: 0,
    truncated: false,
    selfCopy: false,
    solicit: false,
    ignored: false,
    sceneOpen: false,
    labelLeak: false,
    userTurn: false,
    broken: null,
    brackets: [],
    ...overrides,
  };
}

/** 드라이버 줄 한 칸 — `value` 는 바뀐 뒤 값, `delta` 는 측정 서버가 시작 값과 견준 변화량이다. */
function change(name: string, before: number | null, after: number): DriverStatChange {
  return { name, value: after, before, delta: before === null ? null : after - before };
}

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

describe("buildTurnRows", () => {
  it("보충 줄·응답 교체·시도 수·유실을 행에 그대로 싣는다", () => {
    const [row] = buildTurnRows(
      [summary({ turn: 105, supplemented: true, replaced: true, attemptCount: 3, lost: true })],
      [],
    );

    expect(row).toMatchObject({ turn: 105, isSupplemented: true, isReplaced: true, attemptCount: 3, isLost: true });
  });

  it("발화가 없으면 단축어 이름, 둘 다 없으면 발화 없음", () => {
    const rows = buildTurnRows(
      [summary({ turn: 1, userText: null, shortcut: "살펴보기" }), summary({ turn: 2, userText: null })],
      [],
    );

    expect(rows.map((row) => row.utterance)).toEqual([
      { kind: "shortcut", name: "살펴보기" },
      { kind: "none" },
    ]);
  });

  it("플래그는 턴 요약의 응답 지표에서 절단·자기복제·라벨 누출·깨짐 순 약자로, 깨짐만 위험 표시", () => {
    const raised = flags({ broken: "x", labelLeak: true, truncated: true, selfCopy: true, solicit: true });

    const [row] = buildTurnRows([summary({ turn: 1, flags: raised })], []);

    expect(row?.flags.map((flag) => [flag.abbr, flag.isDanger])).toEqual([
      ["절", false],
      ["복", false],
      ["라", false],
      ["깨", true],
    ]);
  });

  it("응답이 없어 지표 표본에서 빠진 턴(지표 없음)이나 아무 플래그도 서지 않은 턴은 플래그가 없다", () => {
    expect(buildTurnRows([summary({ flags: null })], [])[0]?.flags).toEqual([]);
    expect(buildTurnRows([summary({ flags: flags({ solicit: true, sceneOpen: true }) })], [])[0]?.flags).toEqual([]);
  });

  it("깨짐 낱말이 빈 글이어도 깨짐이다 — 깨짐 여부는 낱말이 있는가로 본다", () => {
    expect(buildTurnRows([summary({ flags: flags({ broken: "" }) })], [])[0]?.flags.map((flag) => flag.key)).toEqual([
      "broken",
    ]);
  });

  it("보이는 스탯 Δ 는 계열 순서대로 선 색 셋, 넷째부터는 기타", () => {
    const allSeries = ["호감", "신뢰", "긴장", "의심"].map((name) => series(name));
    const [row] = buildTurnRows(
      [
        summary({
          driverStatChanges: [change("긴장", 40, 54), change("호감", 30, 25), change("의심", 8, 10), change("모름", 0, 1)],
        }),
      ],
      allSeries,
    );

    expect(row?.deltas.map((delta) => [delta.name, delta.tone])).toEqual([
      ["긴장", "series-3"],
      ["호감", "series-1"],
      ["의심", "other"],
      ["모름", "other"],
    ]);
  });

  it("보이는 스탯 Δ 는 서버가 낸 변화량이고, 드라이버 줄의 값(바뀐 뒤 값)은 Δ 가 아니라 바뀐 뒤 값으로 싣는다", () => {
    const [row] = buildTurnRows([summary({ driverStatChanges: [change("긴장", 40, 54)] })], [series("긴장")]);

    expect(row?.deltas).toEqual([{ name: "긴장", delta: 14, before: 40, after: 54, tone: "series-1" }]);
  });

  it("시작 값을 기록으로 알 수 없으면 Δ 를 비운다 — 바뀐 뒤 값을 변화량으로 쓰지 않는다", () => {
    const [row] = buildTurnRows([summary({ driverStatChanges: [change("호감", null, 30)] })], [series("호감")]);

    expect(row?.deltas).toEqual([{ name: "호감", delta: undefined, before: undefined, after: 30, tone: "series-1" }]);
  });

  it("숨김 스탯·드라이버 아닌 계열은 선 색 순서를 차지하지 않는다", () => {
    const tones = seriesTones([
      series("의심", { hidden: true }),
      series("기록만", { source: "chatTurns" }),
      series("호감"),
    ]);

    expect([...tones]).toEqual([["호감", "series-1"]]);
  });

  it("선 자리를 고르면 Δ 점의 색이 고른 자리를 따르고, 자리에서 빠진 스탯은 선이 없어 보조 색이다", () => {
    const four = [series("호감"), series("긴장"), series("신뢰"), series("의심")];
    const tones = seriesTones(four, ["id-의심", "id-긴장", "id-신뢰"]);

    expect([...tones]).toEqual([
      ["호감", "other"],
      ["긴장", "series-2"],
      ["신뢰", "series-3"],
      ["의심", "series-1"],
    ]);
    const [row] = buildTurnRows([summary({ driverStatChanges: [change("의심", 1, 2)] })], four, ["id-의심", "id-긴장", "id-신뢰"]);
    expect(row?.deltas[0]?.tone).toBe("series-1");
  });

  it("숨김 스탯은 턴 기록의 전후 차로 숨김 점을 얻고, 전후 하나라도 비면 Δ 를 만들지 않는다", () => {
    const [row] = buildTurnRows(
      [
        summary({
          recordedStatChanges: [
            { id: "s1", name: "의심", hidden: true, before: 10, after: 25 },
            { id: "s2", name: null, hidden: true, before: null, after: 3 },
            { id: "s3", name: "호감", hidden: false, before: 1, after: 2 },
            { id: "s4", name: null, hidden: true, before: 5, after: 3 },
          ],
        }),
      ],
      [],
    );

    expect(row?.deltas).toEqual([
      { name: "의심", delta: 15, before: 10, after: 25, tone: "hidden" },
      { name: "s4", delta: -2, before: 5, after: 3, tone: "hidden" },
    ]);
  });
});

describe("attemptDeltas", () => {
  const tones = seriesTones([series("호감"), series("긴장")]);
  const [row] = buildTurnRows(
    [
      summary({
        driverStatChanges: [change("호감", 30, 35)],
        recordedStatChanges: [{ id: "s1", name: "의심", hidden: true, before: 1, after: 4 }],
      }),
    ],
    [series("호감"), series("긴장")],
  );

  it("고른 시도는 턴 목록 행과 같은 Δ(숨김 스탯 포함)", () => {
    expect(attemptDeltas(row, attempt({ selected: true, driverStatChanges: [change("긴장", 0, 9)] }), tones)).toBe(
      row?.deltas,
    );
  });

  it("고르지 않은 시도는 그 시도의 드라이버 줄 변화만 — 숨김 스탯은 고른 시도의 턴 기록에만 있다", () => {
    const other = attempt({ index: 2, selected: false, driverStatChanges: [change("긴장", 20, 29)] });

    expect(attemptDeltas(row, other, tones)).toEqual([{ name: "긴장", delta: 9, before: 20, after: 29, tone: "series-2" }]);
  });

  it("시도를 아직 모르면(턴 상세를 받기 전) 행의 Δ, 행도 없으면 빈 목록", () => {
    expect(attemptDeltas(row, undefined, tones)).toBe(row?.deltas);
    expect(attemptDeltas(undefined, undefined, tones)).toEqual([]);
  });
});

describe("formatStatDelta", () => {
  function delta(value: number | undefined): StatDelta {
    return { name: "호감", delta: value, before: value === undefined ? undefined : 10, after: 42, tone: "series-1" };
  }

  it("오르면 +, 내리면 −(빼기 기호), 그대로면 0 — 천 단위 쉼표", () => {
    expect(formatStatDelta(delta(5))).toBe("+5");
    expect(formatStatDelta(delta(-3))).toBe("−3");
    expect(formatStatDelta(delta(0))).toBe("0");
    expect(formatStatDelta(delta(1200))).toBe("+1,200");
  });

  it("변화량을 모르면 바뀐 뒤 값을 적지 않고 Δ 모름", () => {
    expect(formatStatDelta(delta(undefined))).toBe("Δ 모름");
  });
});
