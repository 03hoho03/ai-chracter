import { describe, expect, it } from "vitest";

import type { AttemptDetail, DriverStatChange, ReplyFlagsView, StatSeries, TurnSummary } from "@/shared/api/client";

import { REPLY_FLAG_LABELS } from "./detailLabels";
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

/**
 * 고른 시도의 응답이 `reply` 인 턴. 측정 서버처럼 응답 앞 200자와 길이를 싣고, 응답이 비었는데 교체 줄도 없으면 유실로 센다.
 */
function replied(reply: string, overrides: Partial<TurnSummary> = {}): TurnSummary {
  const isReplaced = overrides.replaced ?? false;
  return summary({
    replyHead: reply.slice(0, 200),
    replyLength: reply.length,
    lost: reply === "" && !isReplaced,
    ...overrides,
  });
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
  it("보충 줄·응답 교체·시도 수를 행에 그대로 싣는다 — 응답이 없는 턴은 응답 한 줄이 그 까닭을 싣는다", () => {
    const [row] = buildTurnRows([summary({ turn: 105, supplemented: true, replaced: true, attemptCount: 3 })], []);

    expect(row).toMatchObject({ turn: 105, isSupplemented: true, isReplaced: true, attemptCount: 3 });
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

  it("행 플래그의 온 이름은 검사기·'먼저 볼 것'과 같은 응답 플래그 이름표에서 온다", () => {
    const raised = flags({ truncated: true, selfCopy: true, labelLeak: true, broken: "x" });

    const [row] = buildTurnRows([summary({ flags: raised })], []);

    expect(row?.flags.map((flag) => [flag.key, flag.label])).toEqual(
      (["truncated", "selfCopy", "labelLeak", "broken"] as const).map((key) => [key, REPLY_FLAG_LABELS[key]]),
    );
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

describe("buildTurnRows 의 응답 한 줄", () => {
  function replyLine(turn: TurnSummary) {
    return buildTurnRows([turn], [])[0]?.reply;
  }

  it("응답이 있으면 그 앞부분을 싣는다", () => {
    expect(replyLine(replied("그가 고개를 들어 문 쪽을 본다."))).toEqual({
      kind: "reply",
      text: "그가 고개를 들어 문 쪽을 본다.",
    });
  });

  it("줄바꿈·탭·겹친 공백은 빈칸 하나로 접고 앞뒤 공백을 뗀다 — 행에서 한 줄로 읽힌다", () => {
    expect(replyLine(replied('\n  그가 고개를 든다.\n\n\t"누구세요?"  \n'))).toEqual({
      kind: "reply",
      text: '그가 고개를 든다. "누구세요?"',
    });
  });

  it("응답이 있으면 실패 문장이 함께 있어도 응답을 보인다", () => {
    expect(replyLine(replied("문이 열린다.", { failure: "error: 판정 지연" }))?.kind).toBe("reply");
  });

  it("응답 없이 실패로 끝났으면 빈칸 대신 실패 문장을 한 줄로 접어 까닭으로 보이고, 유실한 턴이라고 싣는다", () => {
    expect(replyLine(replied("", { failure: 'HTTP 500: {"detail":\n  "서버 오류"}' }))).toEqual({
      kind: "failure",
      text: 'HTTP 500: {"detail": "서버 오류"}',
      isLost: true,
    });
  });

  it("응답이 공백뿐인데 실패 문장이 있으면 실패 문장을 보이되 유실이라 하지 않는다 — 측정 서버도 응답이 온 턴으로 센다", () => {
    const blankWithFailure = replied(" \n ", { failure: "error: 판정 지연" });

    expect(blankWithFailure.lost).toBe(false);
    expect(replyLine(blankWithFailure)).toEqual({ kind: "failure", text: "error: 판정 지연", isLost: false });
  });

  it("응답도 실패 문장도 없으면 응답 없음 — 실패 문장이 공백뿐이어도 같다", () => {
    expect(replyLine(replied(""))).toEqual({ kind: "none" });
    expect(replyLine(replied("", { failure: " \n " }))).toEqual({ kind: "none" });
  });

  it("응답이 공백뿐이면 빈 응답 — 응답이 오지 않은 턴(유실)과 가른다", () => {
    const blank = replied(" \n\n ");

    expect(blank.lost).toBe(false);
    expect(replyLine(blank)).toEqual({ kind: "blank" });
  });

  it("측정 서버가 주는 앞부분만 공백이고 그 뒤에 글이 이어지면 빈 응답이라 하지 않고 앞부분이 공백뿐이라고", () => {
    const lateText = replied(`${" ".repeat(200)}그가 고개를 든다.`);

    expect(lateText.replyLength).toBeGreaterThan(lateText.replyHead.length);
    expect(replyLine(lateText)).toEqual({ kind: "blankHead" });
  });

  it("응답이 교체됐어도 고른 시도에 응답이 있으면(앞부분만 공백) 앞부분이 공백뿐이라고 — 교체 사실은 교체 표지가 따로 보인다", () => {
    // 측정 서버는 성공한 재생성·수정 줄이 있으면 고른 시도의 응답 유무와 상관없이 교체로 보고, 응답 앞부분·길이는 고른 시도에서 낸다.
    const [row] = buildTurnRows([replied(`${" ".repeat(200)}그가 고개를 든다.`, { replaced: true })], []);

    expect(row?.isReplaced).toBe(true);
    expect(row?.reply).toEqual({ kind: "blankHead" });
  });

  it("고른 시도에 응답이 없어도 응답이 교체됐으면 유실이 아니라 응답이 교체 줄에 있다고 보인다", () => {
    const replaced = replied("", { replaced: true });

    expect(replaced.lost).toBe(false);
    expect(replyLine(replaced)).toEqual({ kind: "replaced" });
  });

  it("교체됐어도 고른 시도가 실패로 끝났으면 실패 문장을 보이되, 교체 줄이 응답을 냈으니 유실이라 하지 않는다", () => {
    const replacedFailure = replied("", { replaced: true, failure: "transport: ReadTimeout: timed out" });

    expect(replacedFailure.lost).toBe(false);
    expect(replyLine(replacedFailure)).toEqual({
      kind: "failure",
      text: "transport: ReadTimeout: timed out",
      isLost: false,
    });
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
