import { describe, expect, it } from "vitest";

import type { TurnMetrics } from "@/shared/api/client";

import { BOOLEAN_FLAG_KEYS, BOOLEAN_FLAG_LABELS, describePreviousFrom, MARKER_STYLES } from "./detailLabels";

function turnMetrics(previousFrom: TurnMetrics["previousFrom"], previousTurn: number | null): TurnMetrics {
  return {
    turn: 5,
    flags: {
      length: 1,
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
    },
    previousFrom,
    previousTurn,
  };
}

describe("describePreviousFrom", () => {
  it("직전 응답이 어디서 왔는지 — 오프닝·앞 턴·교체 뒤 응답·없음", () => {
    expect(describePreviousFrom(turnMetrics("opening", null))).toBe("오프닝 마지막 메시지");
    expect(describePreviousFrom(turnMetrics("turn", 4))).toBe("턴 4 응답");
    expect(describePreviousFrom(turnMetrics("replacement", 4))).toBe("턴 4 교체 뒤 응답");
    expect(describePreviousFrom(turnMetrics("none", null))).toBe("없음");
  });

  it("앞 턴 번호가 비면 물음표로 — 번호를 지어내지 않는다", () => {
    expect(describePreviousFrom(turnMetrics("turn", null))).toBe("턴 ? 응답");
    expect(describePreviousFrom(turnMetrics("replacement", null))).toBe("턴 ? 교체 뒤 응답");
  });
});

describe("BOOLEAN_FLAG_KEYS", () => {
  it("참/거짓 지표만, 이름표의 순서대로 — 길이·문장 수·깨짐·괄호는 값이 다른 모양이라 빠진다", () => {
    expect(BOOLEAN_FLAG_KEYS).toEqual(["truncated", "selfCopy", "labelLeak", "userTurn", "solicit", "ignored", "sceneOpen"]);
    expect(BOOLEAN_FLAG_KEYS).toEqual(Object.keys(BOOLEAN_FLAG_LABELS));
  });
});

describe("MARKER_STYLES", () => {
  it("드라이버 줄에서 온 표지(rebase·점검·노트 저장·멈춤)만 그 턴 뒤 칸에 놓는다", () => {
    const afterTurn = Object.entries(MARKER_STYLES)
      .filter(([, style]) => style.isAfterTurn)
      .map(([kind]) => kind)
      .sort();

    expect(afterTurn).toEqual(["check", "noteUpdate", "pause", "rebase"]);
  });

  it("실패만 적색, rebase·재생성·수정은 호박, 나머지는 흐린 글자색", () => {
    const tones = Object.fromEntries(Object.entries(MARKER_STYLES).map(([kind, style]) => [kind, style.tone]));

    expect(tones).toEqual({
      ending: "muted",
      noteChange: "muted",
      summaryUpdate: "muted",
      rebase: "warn",
      regenerate: "warn",
      edit: "warn",
      check: "muted",
      noteUpdate: "muted",
      pause: "muted",
      failure: "danger",
    });
  });

  it("표지마다 모양이 다르다 — 낱말과 함께 모양으로도 갈린다", () => {
    const glyphs = Object.values(MARKER_STYLES).map((style) => style.glyph);

    expect(new Set(glyphs).size).toBe(glyphs.length);
  });
});
