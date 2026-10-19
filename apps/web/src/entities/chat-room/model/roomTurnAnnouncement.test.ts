import { describe, expect, it } from "vitest";

import type { ChatRoomState, StatDef } from "./chatRoomState";
import { buildRoomTurnAnnouncement, expandRoomStats } from "./roomTurnAnnouncement";
import { HIDDEN_STAT_SIGNAL_TEXT } from "./statTurnFeedback";

const TRUST: StatDef = {
  id: "trust",
  name: "{{user}}의 신뢰",
  icon: "Heart",
  color: "#f00",
  min: 0,
  max: 100,
  initial: 10,
  unit: "{{user}}점",
  playerDescription: "{{user}}를 믿는 정도",
};

type AnnouncementRoom = Parameters<typeof buildRoomTurnAnnouncement>[0];

function room(overrides: Partial<ChatRoomState> = {}): AnnouncementRoom {
  return {
    contentType: "story",
    personaName: "민지",
    contentName: "폐광",
    hasMoreMessagesBefore: false,
    stats: { trust: 13 },
    messages: [
      { id: "o", role: "assistant", content: "", createdAt: "" },
      { id: "u1", role: "user", content: "", createdAt: "" },
      { id: "a1", role: "assistant", content: "", createdAt: "", scene: { place: "{{user}}의 방", time: "새벽" } },
    ],
    contentSnapshot: {
      stats: [TRUST],
      endings: [],
      shortcuts: [],
      suggestedReplies: [],
      pinnedStartingSetupId: "setup",
      sceneHeaderEnabled: true,
      initialScene: { place: "입구", time: "밤" },
    },
    ...overrides,
  };
}

describe("expandRoomStats", () => {
  it("스탯 이름·단위·플레이어용 설명의 작가 매크로를 방의 이름으로 펼친다", () => {
    const [expanded] = expandRoomStats([TRUST], { userName: "민지", charName: null });
    expect(expanded).toMatchObject({ name: "민지의 신뢰", unit: "민지점", playerDescription: "민지를 믿는 정도" });
  });
});

describe("buildRoomTurnAnnouncement", () => {
  it("스크린리더 안내도 화면처럼 펼친 이름을 읽는다 — 매크로 원문이 남지 않는다", () => {
    const announcement = buildRoomTurnAnnouncement(room(), { deltas: { trust: 3 }, hiddenSignal: false }, {
      place: "입구",
      time: "밤",
    });
    expect(announcement).toBe("민지의 신뢰 3 올라 13민지점. 장소 바뀜: 민지의 방. 시간 바뀜: 새벽");
    expect(announcement).not.toContain("{{");
  });

  it("공개 스탯 증감 → 장면 변화 → 익명 신호 순서로 잇는다", () => {
    expect(
      buildRoomTurnAnnouncement(room(), { deltas: {}, hiddenSignal: true }, { place: "입구", time: "새벽" }),
    ).toBe(`장소 바뀜: 민지의 방. ${HIDDEN_STAT_SIGNAL_TEXT}`);
  });

  it("장면 헤더를 끈 작품은 장면을 읽지 않는다", () => {
    const snapshot = room().contentSnapshot;
    const off = room({ contentSnapshot: snapshot && { ...snapshot, sceneHeaderEnabled: false } });
    expect(buildRoomTurnAnnouncement(off, { deltas: {}, hiddenSignal: false }, undefined)).toBe("");
  });
});
