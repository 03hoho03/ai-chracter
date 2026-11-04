import { describe, expect, it } from "vitest";

import type { TurnMetrics } from "@/shared/api/client";

import {
  BOOLEAN_FLAG_KEYS,
  BOOLEAN_FLAG_LABELS,
  describePreviousFrom,
  INSPECTOR_TAB_OPTIONS,
  MARKER_STYLES,
  NARROW_PANE_OPTIONS,
  REPLY_FLAG_LABELS,
} from "./detailLabels";
import { INSPECTOR_TABS, PANES } from "./runDetailSearch";

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

describe("REPLY_FLAG_LABELS", () => {
  it("참/거짓 지표 이름을 그대로 싣고 깨짐·괄호를 더한다 — 턴 목록 행·'먼저 볼 것'·검사기가 플래그 이름을 여기서 읽는다", () => {
    expect(REPLY_FLAG_LABELS).toEqual({ ...BOOLEAN_FLAG_LABELS, broken: "깨짐", brackets: "괄호" });
  });
});

describe("INSPECTOR_TAB_OPTIONS", () => {
  it("검사기 탭 머리는 숫자 단축키가 따르는 탭 목록에서 만든다 — 같은 탭, 같은 순서", () => {
    expect(INSPECTOR_TAB_OPTIONS.map((option) => option.tab)).toEqual(INSPECTOR_TABS);
  });

  it("탭 이름은 호출·기억·라우팅·지표", () => {
    expect(Object.fromEntries(INSPECTOR_TAB_OPTIONS.map((option) => [option.tab, option.label]))).toEqual({
      calls: "호출",
      memory: "기억",
      routing: "라우팅",
      metrics: "지표",
    });
  });
});

describe("NARROW_PANE_OPTIONS", () => {
  it("좁은 화면의 칸 고르기는 칸 목록 전부를 그 순서대로 덮는다", () => {
    expect(NARROW_PANE_OPTIONS.map((option) => option.pane)).toEqual(PANES);
  });

  it("칸 이름은 턴·대화·호출", () => {
    expect(Object.fromEntries(NARROW_PANE_OPTIONS.map((option) => [option.pane, option.label]))).toEqual({
      turns: "턴",
      conversation: "대화",
      inspector: "호출",
    });
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
      supplemented: "muted",
    });
  });

  it("표지마다 모양이 다르다 — 낱말과 함께 모양으로도 갈린다", () => {
    const glyphs = Object.values(MARKER_STYLES).map((style) => style.glyph);

    expect(new Set(glyphs).size).toBe(glyphs.length);
  });
});
