import { describe, expect, it } from "vitest";

import type { StatDef } from "./chatRoomState";
import {
  addStatDelta,
  buildStatTurnAnnouncement,
  formatStatDelta,
  formatStatValue,
  HIDDEN_STAT_SIGNAL_TEXT,
  selectVisibleTurnFeedback,
  type StatTurnFeedback,
} from "./statTurnFeedback";

function stat(overrides: Partial<StatDef> = {}): StatDef {
  return { id: "aff", name: "호감도", icon: "Heart", color: "#f00", min: 0, max: 100, initial: 37, ...overrides };
}

describe("addStatDelta", () => {
  it("캐시의 직전 값과 새 값의 차를 그 스탯의 증감으로 적는다", () => {
    expect(addStatDelta({}, "aff", 45, 48)).toEqual({ aff: 3 });
    expect(addStatDelta({ aff: 3 }, "hp", 48, 41)).toEqual({ aff: 3, hp: -7 });
  });

  it("직전 값을 모르면(캐시에 없으면) 적지 않는다 — 재접속·새로고침 뒤의 첫 값은 증감이 아니다", () => {
    expect(addStatDelta({}, "aff", undefined, 48)).toEqual({});
  });

  it("값이 그대로면(경계에 막혔을 때) 적지 않고, 한 턴에 두 번 오면 더해서 0이 되면 지운다", () => {
    expect(addStatDelta({}, "aff", 100, 100)).toEqual({});
    expect(addStatDelta({ aff: 3 }, "aff", 48, 51)).toEqual({ aff: 6 });
    expect(addStatDelta({ aff: 3 }, "aff", 48, 45)).toEqual({});
  });
});

describe("formatStatDelta", () => {
  it("오르면 +, 내리면 수학 기호 마이너스(U+2212)를 붙인다 — 방향을 색이 아니라 기호가 진다", () => {
    expect(formatStatDelta(3)).toBe("+3");
    expect(formatStatDelta(-7)).toBe("−7");
  });
});

describe("formatStatValue", () => {
  it("값/최대에 단위를 붙이고, 퍼센트 단위는 최대 없이 값에 바로 붙인다", () => {
    expect(formatStatValue(stat(), 48)).toEqual({ value: "48", rest: "/100" });
    expect(formatStatValue(stat({ max: 5, unit: "명" }), 3)).toEqual({ value: "3", rest: "/5명" });
    expect(formatStatValue(stat({ unit: "%" }), 62)).toEqual({ value: "62", rest: "%" });
  });

  it("짧은 꼴은 최대를 접는다(증감 칩이 떠 있는 동안 이름 칸을 지키려고)", () => {
    expect(formatStatValue(stat(), 48, { short: true })).toEqual({ value: "48", rest: "" });
    expect(formatStatValue(stat({ max: 5, unit: "명" }), 3, { short: true })).toEqual({ value: "3", rest: "명" });
  });
});

describe("buildStatTurnAnnouncement", () => {
  const stats = [stat(), stat({ id: "hp", name: "체력" }), stat({ id: "bat", name: "손전등 배터리", unit: "%" })];

  it("바뀐 스탯을 정의 순서대로 한 문장씩 잇고, 단위가 있으면 붙인다", () => {
    expect(
      buildStatTurnAnnouncement(stats, { aff: 48, hp: 41, bat: 52 }, { deltas: { bat: -10, aff: 3 }, hiddenSignal: false }),
    ).toBe("호감도 3 올라 48. 손전등 배터리 10 내려 52%");
  });

  it("숨긴 스탯 신호는 맨 뒤에 붙고, 신호만 있으면 그 말만 읽는다", () => {
    expect(buildStatTurnAnnouncement(stats, { aff: 48 }, { deltas: { aff: 3 }, hiddenSignal: true })).toBe(
      `호감도 3 올라 48. ${HIDDEN_STAT_SIGNAL_TEXT}`,
    );
    expect(buildStatTurnAnnouncement(stats, {}, { deltas: {}, hiddenSignal: true })).toBe(HIDDEN_STAT_SIGNAL_TEXT);
  });

  it("정의에 없는 스탯의 증감은 읽지 않고, 바뀐 것이 없으면 빈 글이다", () => {
    expect(buildStatTurnAnnouncement(stats, {}, { deltas: { gone: 5 }, hiddenSignal: false })).toBe("");
  });
});

describe("selectVisibleTurnFeedback", () => {
  const feedback: StatTurnFeedback = {
    turn: 1,
    roomId: "room-a",
    messageId: "ai-2",
    deltas: { aff: 3 },
    hiddenSignal: true,
    announcement: `호감도 3 올라 48. ${HIDDEN_STAT_SIGNAL_TEXT}`,
  };
  const messages = [
    { id: "ai-1", role: "assistant" as const },
    { id: "user-1", role: "user" as const },
    { id: "ai-2", role: "assistant" as const },
  ];

  it("지금 방이고 캐시의 마지막 AI 메시지가 그 턴의 응답이면 알림을 그대로 보인다", () => {
    expect(selectVisibleTurnFeedback(feedback, "room-a", messages)).toBe(feedback);
  });

  it("다른 방으로 옮기면 보이지 않는다 — 같은 스토리의 방이라 스탯 id 가 같아도", () => {
    expect(selectVisibleTurnFeedback(feedback, "room-b", messages)).toBeUndefined();
  });

  it("되돌리기·초기화·삭제로 마지막 AI 메시지가 그 응답이 아니게 되면 보이지 않는다", () => {
    const restored = [...messages.slice(0, 2), { id: "ai-2-old", role: "assistant" as const }];
    expect(selectVisibleTurnFeedback(feedback, "room-a", restored)).toBeUndefined();
    expect(selectVisibleTurnFeedback(feedback, "room-a", [{ id: "opening", role: "assistant" as const }])).toBeUndefined();
    expect(selectVisibleTurnFeedback(feedback, "room-a", [])).toBeUndefined();
  });

  it("응답 뒤에 사용자 메시지가 붙어도 마지막 AI 메시지로 가린다 — 다음 턴이 시작되면 훅이 알림을 거둔다", () => {
    expect(selectVisibleTurnFeedback(feedback, "room-a", [...messages, { id: "user-2", role: "user" as const }])).toBe(
      feedback,
    );
  });

  it("알림이 없으면 없다", () => {
    expect(selectVisibleTurnFeedback(undefined, "room-a", messages)).toBeUndefined();
  });
});
