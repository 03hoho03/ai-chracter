import { describe, expect, it } from "vitest";

import type { TimelineMarker } from "@/shared/api/client";

import { indexAtRatio, placeMarkers, tickIndexes } from "./timelineMarks";

function marker(kind: TimelineMarker["kind"], turn: number, detail: string | null = null): TimelineMarker {
  return { kind, turn, detail };
}

describe("placeMarkers", () => {
  it("턴 표지는 그 턴 칸 가운데, 드라이버 줄 표지는 그 턴과 다음 턴 사이에 놓는다", () => {
    const groups = placeMarkers([1, 2, 3, 4], [marker("ending", 2, "새벽"), marker("rebase", 2, "기준 다시 잡기")], []);

    expect(groups.map((group) => [group.position, group.index, group.isAfterTurn, group.glyphs])).toEqual([
      [0.375, 1, false, "◆"],
      [0.5, 1, true, "↺"],
    ]);
    expect(groups[1]?.title).toBe("턴 2 뒤 · rebase — 기준 다시 잡기");
  });

  it("같은 자리 표지는 한 묶음으로 — 모양을 잇고 낱말을 모두 싣고, 색은 가장 무거운 것을 따른다", () => {
    const [group, ...rest] = placeMarkers(
      [1, 2, 3],
      [marker("noteChange", 3), marker("summaryUpdate", 3), marker("failure", 3, "생성 실패")],
      [],
    );

    expect(rest).toEqual([]);
    expect(group).toEqual({
      key: "at:2",
      index: 2,
      isAfterTurn: false,
      position: 5 / 6,
      glyphs: "●■✕",
      tone: "danger",
      title: "턴 3 · 기억 노트 변경 · 요약 갱신 · 실패 — 생성 실패",
    });
  });

  it("호박 표지와 흐린 표지가 섞이면 호박이다", () => {
    expect(placeMarkers([1], [marker("ending", 1), marker("regenerate", 1)], [])[0]?.tone).toBe("warn");
  });

  it("보충 줄 턴에 보충 표지를 둔다 — 같은 턴의 서버 표지와 한 묶음", () => {
    const [group] = placeMarkers([1, 2], [marker("ending", 2)], [2]);

    expect([group?.glyphs, group?.title]).toEqual(["◆+", "턴 2 · 엔딩 · 보충 줄"]);
  });

  it("런 안쪽 번호 공백의 '턴 뒤' 표지는 그 번호보다 큰 첫 칸의 앞 경계에 놓고, 그 경계의 표지와 한 묶음이다", () => {
    const alone = placeMarkers([1, 2, 5], [marker("rebase", 4, "사람 구간 뒤")], []);
    const [group, ...rest] = placeMarkers([1, 2, 5], [marker("noteUpdate", 2), marker("rebase", 4, "사람 구간 뒤")], []);

    expect(alone.map((entry) => [entry.key, entry.index, entry.position])).toEqual([["after:1", 1, 2 / 3]]);
    expect(rest).toEqual([]);
    expect(group).toEqual({
      key: "after:1",
      index: 1,
      isAfterTurn: true,
      position: 2 / 3,
      glyphs: "✐↺",
      tone: "warn",
      title: "턴 2 뒤 · 노트 저장 · 턴 4 뒤 rebase — 사람 구간 뒤",
    });
  });

  it("런에 없는 턴의 표지는 가까운 쪽 끝에 놓는다", () => {
    const groups = placeMarkers([5, 6], [marker("rebase", 9), marker("check", 1)], []);

    expect(groups.map((group) => [group.position, group.index])).toEqual([
      [0, -1],
      [1, -1],
    ]);
  });
});

describe("tickIndexes", () => {
  it("칸이 적으면 모든 칸, 많으면 처음·끝과 간격마다 — 끝과 너무 붙은 눈금은 뺀다", () => {
    expect(tickIndexes(0)).toEqual([]);
    expect(tickIndexes(1)).toEqual([0]);
    expect(tickIndexes(5)).toEqual([0, 1, 2, 3, 4]);
    expect(tickIndexes(120)).toEqual([0, 9, 19, 29, 39, 49, 59, 69, 79, 89, 99, 109, 119]);
    expect(tickIndexes(24)).toEqual([0, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23]);
    // 5칸 간격의 마지막 눈금(54)이 끝(56)과 두 칸뿐이라 뺀다.
    expect(tickIndexes(57)).toEqual([0, 4, 9, 14, 19, 24, 29, 34, 39, 44, 49, 56]);
  });
});

describe("indexAtRatio", () => {
  it("가로 비율을 그 칸 순번으로 — 양 끝 밖은 끝 칸, 칸이 없으면 없다", () => {
    expect(indexAtRatio(0.5, 10)).toBe(5);
    expect(indexAtRatio(0.999, 10)).toBe(9);
    expect(indexAtRatio(1.2, 10)).toBe(9);
    expect(indexAtRatio(-0.1, 10)).toBe(0);
    expect(indexAtRatio(0.5, 0)).toBeUndefined();
  });
});
