import { describe, expect, it } from "vitest";

import type { StatSeries } from "@/shared/api/client";

import {
  buildChartModel,
  buildStrips,
  heldValueAt,
  niceScale,
  placeEndLabels,
  stripsLabel,
  type ChartLine,
} from "./timelineChart";

type TurnStart = { turn: number; statsContinueFromPrevious: boolean };

/** 칸들 — `broken` 에 든 턴은 측정 서버가 앞 번호 턴에서 이어지지 않는다고 한 턴이다. */
function turns(numbers: ReadonlyArray<number>, broken: ReadonlyArray<number> = []): TurnStart[] {
  return numbers.map((turn) => ({ turn, statsContinueFromPrevious: !broken.includes(turn) }));
}

function series(id: string, points: ReadonlyArray<[number, number]>, overrides: Partial<StatSeries> = {}): StatSeries {
  return {
    id,
    name: `이름-${id}`,
    hidden: false,
    source: "driver",
    points: points.map(([turn, value]) => ({ turn, value })),
    ...overrides,
  };
}

/** 턴 기록에서만 온 숨김 계열 — 점마다 그 행의 앞 값을 실을 수 있다. */
function hidden(id: string, points: ReadonlyArray<{ turn: number; value: number; before?: number }>): StatSeries {
  return { id, name: `이름-${id}`, hidden: true, source: "chatTurns", points: points.map((point) => ({ ...point })) };
}

/** 한 선의 두 데이터 키 값을 칸 순서대로. */
function column(rows: ReadonlyArray<Readonly<Record<string, number | null>>>, key: string): Array<number | null> {
  return rows.map((row) => row[key] ?? null);
}

describe("buildChartModel", () => {
  it("값이 이어지고 앞 번호 턴에서 이어지는 턴만 있으면 한 토막 — 첫 키에 모두, 둘째 키는 비고 따로 그릴 점도 없다", () => {
    const model = buildChartModel(turns([1, 2, 3]), [series("a", [[1, 50], [2, 60], [3, 55]])], ["a"]);
    const [line] = model.lines;

    expect(line?.keys).toEqual(["a:0", "a:1"]);
    expect(column(model.rows, "a:0")).toEqual([50, 60, 55]);
    expect(column(model.rows, "a:1")).toEqual([null, null, null]);
    expect(model.rows.map((row) => row.index)).toEqual([0, 1, 2]);
    expect([...model.isolated]).toEqual([]);
  });

  it("값이 없는 턴에서 선이 끊기고, 앞뒤와 이어지지 않는 점은 따로 그릴 점이 된다 — 없는 값을 0 으로 잇지 않는다", () => {
    const model = buildChartModel(turns([1, 2, 3]), [series("a", [[1, 50], [3, 70]])], ["a"]);

    expect(model.lines[0]?.values).toEqual([50, null, 70]);
    expect(column(model.rows, "a:0")).toEqual([50, null, null]);
    expect(column(model.rows, "a:1")).toEqual([null, null, 70]);
    expect([...model.isolated].sort()).toEqual(["a:0:0", "a:1:2"]);
  });

  it("앞 번호 턴에서 이어지지 않는 턴(시작 값 모름·다른 값으로 기준 다시 잡음)으로 들어오는 선분만 끊는다 — 점은 남는다", () => {
    const model = buildChartModel(
      turns([1, 2, 3, 4], [3]),
      [series("a", [[1, 50], [2, 80], [3, 40], [4, 45]])],
      ["a"],
    );

    expect(column(model.rows, "a:0")).toEqual([50, 80, null, null]);
    expect(column(model.rows, "a:1")).toEqual([null, null, 40, 45]);
    expect([...model.isolated]).toEqual([]);
  });

  it("세 번째 토막은 첫 키로 돌아오되, 둘째 토막 칸이 그 사이를 비워 첫 토막과 이어지지 않는다", () => {
    const model = buildChartModel(
      turns([1, 2, 3, 4, 5], [3, 5]),
      [series("a", [[1, 1], [2, 2], [3, 3], [4, 4], [5, 5]])],
      ["a"],
    );

    expect(column(model.rows, "a:0")).toEqual([1, 2, null, null, 5]);
    expect(column(model.rows, "a:1")).toEqual([null, null, 3, 4, null]);
    expect([...model.isolated]).toEqual(["a:0:4"]);
  });

  it("가로 자리는 턴 번호가 아니라 칸 순번이다 — 런에 없는 턴의 점은 버리고, 번호가 건너뛴 칸 사이는 잇지 않는다", () => {
    // 턴 5 가 이어진다고 적혀 있어도 앞 칸이 바로 앞 번호(4)가 아니면 끊는다.
    const model = buildChartModel(turns([1, 2, 5]), [series("a", [[1, 10], [2, 20], [4, 99], [5, 30]])], ["a"]);

    expect(model.lines[0]?.values).toEqual([10, 20, 30]);
    expect(column(model.rows, "a:0")).toEqual([10, 20, null]);
    expect(column(model.rows, "a:1")).toEqual([null, null, 30]);
    expect([...model.isolated]).toEqual(["a:1:2"]);
  });

  it("바로 앞 번호 칸이어도 측정 서버가 이어지지 않는다고 하면 끊는다", () => {
    const model = buildChartModel(turns([1, 2], [2]), [series("a", [[1, 10], [2, 20]])], ["a"]);

    expect(column(model.rows, "a:0")).toEqual([10, null]);
    expect(column(model.rows, "a:1")).toEqual([null, 20]);
    expect([...model.isolated].sort()).toEqual(["a:0:0", "a:1:1"]);
  });

  it("선 순서와 색은 고른 자리를 따르고, 자리에 없는 스탯과 숨김 스탯은 선이 되지 않는다", () => {
    const model = buildChartModel(
      turns([1]),
      [series("a", [[1, 1]]), series("b", [[1, 2]]), series("c", [[1, 3]]), series("h", [[1, 4]], { hidden: true })],
      ["c", "a"],
    );

    expect(model.lines.map((line: ChartLine) => [line.id, line.tone])).toEqual([
      ["c", "series-1"],
      ["a", "series-2"],
    ]);
  });

  it("세로 범위는 그린 선의 값만으로 잡는다", () => {
    const model = buildChartModel(turns([1, 2]), [series("a", [[1, 40], [2, 80]]), series("b", [[1, 0], [2, 100]])], ["a"]);

    expect(model.domain).toEqual([40, 80]);
  });
});

describe("niceScale", () => {
  it("끝을 깔끔한 눈금으로 넓히고 눈금은 둘~넷 칸이다", () => {
    expect(niceScale([40, 80])).toEqual({ domain: [40, 80], ticks: [40, 60, 80] });
    expect(niceScale([50, 80])).toEqual({ domain: [40, 80], ticks: [40, 60, 80] });
    expect(niceScale([0, 100])).toEqual({ domain: [0, 100], ticks: [0, 50, 100] });
    expect(niceScale([3, 7])).toEqual({ domain: [2, 8], ticks: [2, 4, 6, 8] });
    expect(niceScale([0, 50])).toEqual({ domain: [0, 50], ticks: [0, 25, 50] });
  });

  it("값이 하나뿐이면 그 값을 가운데 두고 넓힌다 — 범위 0 으로 나누지 않는다", () => {
    expect(niceScale([50, 50])).toEqual({ domain: [45, 55], ticks: [45, 50, 55] });
    expect(niceScale([0])).toEqual({ domain: [-1, 1], ticks: [-1, 0, 1] });
  });

  it("값이 없으면 눈금도 없다", () => {
    expect(niceScale([])).toEqual({ domain: [0, 1], ticks: [] });
  });
});

describe("placeEndLabels", () => {
  function line(id: string, values: Array<number | null>): ChartLine {
    return { id, name: `이름-${id}`, tone: "series-1", keys: [`${id}:0`, `${id}:1`], values };
  }

  it("마지막 값 자리에 이름표를 두고, 앞선 이름표와 겹치면 그 이름표만 숨긴다(범례가 이름을 싣는다)", () => {
    const labels = placeEndLabels([line("a", [50, 80]), line("b", [60, 78]), line("c", [70, 40])], [40, 80]);

    expect(labels).toEqual([
      { id: "a", name: "이름-a", tone: "series-1", t: 1, isShown: true },
      { id: "b", name: "이름-b", tone: "series-1", t: 0.95, isShown: false },
      { id: "c", name: "이름-c", tone: "series-1", t: 0, isShown: true },
    ]);
  });

  it("값이 하나도 없는 선은 이름표가 없고, 끝이 비어도 마지막으로 값이 있는 칸을 쓴다", () => {
    expect(placeEndLabels([line("a", [null, null]), line("b", [55, 60, null])], [40, 80])).toEqual([
      { id: "b", name: "이름-b", tone: "series-1", t: 0.5, isShown: true },
    ]);
  });
});

describe("buildStrips", () => {
  it("선 후보가 아닌 계열(숨김·턴 기록에서만)을 칸 순번으로 놓고, 바뀐 턴의 점과 다음 변화·마지막 칸까지의 유지 구간을 낸다", () => {
    const [strip] = buildStrips(turns([1, 2, 3, 4]), [
      series("a", [[1, 1]]),
      series("h", [[2, 10], [4, 30]], { hidden: true, source: "chatTurns" }),
    ]);

    expect(strip?.id).toBe("h");
    expect(strip?.tag).toBe("hidden");
    expect(strip?.dots).toEqual([
      { index: 1, value: 10, t: 0 },
      { index: 3, value: 30, t: 1 },
    ]);
    // 마지막 변화가 마지막 칸이면 유지 구간이 없다.
    expect(strip?.holds).toEqual([{ from: 1, to: 3, t: 0, value: 10 }]);
  });

  it("유지 구간은 번호 공백에서 끊긴다 — 사람이 친 구간 동안 값이 이어졌다고 말하지 않는다", () => {
    const [strip] = buildStrips(turns([1, 2, 3, 6, 7]), [hidden("h", [{ turn: 1, value: 20 }])]);

    expect(strip?.holds).toEqual([{ from: 0, to: 2, t: 0.5, value: 20 }]);
    expect(strip && [2, 3, 4].map((index) => heldValueAt(strip, index))).toEqual([20, undefined, undefined]);
  });

  it("다음 변화의 앞 값이 유지 값과 다르면 그 유지 구간 전체를 끊고, 같으면 잇는다", () => {
    const [broken] = buildStrips(turns([1, 2, 3, 4]), [
      hidden("h", [{ turn: 1, value: 20 }, { turn: 4, value: 40, before: 35 }]),
    ]);
    const [kept] = buildStrips(turns([1, 2, 3, 4]), [
      hidden("h", [{ turn: 1, value: 20 }, { turn: 4, value: 40, before: 20 }]),
    ]);

    expect(broken?.holds).toEqual([]);
    expect(broken && [0, 1, 2, 3].map((index) => heldValueAt(broken, index))).toEqual([20, undefined, undefined, 40]);
    expect(kept?.holds).toEqual([{ from: 0, to: 3, t: 0, value: 20 }]);
    expect(kept && heldValueAt(kept, 2)).toBe(20);
  });

  it("숨김 여부를 모르는 계열과 보이는 스탯인데 턴 기록에서만 온 계열은 그 사실을 표지로 갖는다", () => {
    const strips = buildStrips(turns([1]), [
      series("u", [[1, 5]], { hidden: null, source: "chatTurns" }),
      series("r", [[1, 5]], { hidden: false, source: "chatTurns" }),
    ]);

    expect(strips.map((strip) => [strip.id, strip.tag, strip.dots[0]?.t])).toEqual([
      ["u", "unknown", 0.5],
      ["r", "recordOnly", 0.5],
    ]);
  });
});

describe("heldValueAt", () => {
  it("그 칸 이하에서 마지막으로 바뀐 값 — 첫 변화 앞은 모른다", () => {
    const [strip] = buildStrips(turns([1, 2, 3]), [series("h", [[2, 10]], { hidden: true, source: "chatTurns" })]);

    expect(strip && [heldValueAt(strip, 0), heldValueAt(strip, 1), heldValueAt(strip, 2)]).toEqual([undefined, 10, 10]);
  });
});

describe("stripsLabel", () => {
  it("모두 숨김이면 숨김 스탯, 아니면 턴 기록 스탯", () => {
    const hidden = buildStrips(turns([1]), [series("h", [[1, 1]], { hidden: true, source: "chatTurns" })]);
    const mixed = buildStrips(turns([1]), [
      series("h", [[1, 1]], { hidden: true, source: "chatTurns" }),
      series("r", [[1, 1]], { hidden: false, source: "chatTurns" }),
    ]);

    expect(stripsLabel(hidden)).toBe("숨김 스탯");
    expect(stripsLabel(mixed)).toBe("턴 기록 스탯");
  });
});
