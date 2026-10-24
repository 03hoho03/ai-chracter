import { describe, expect, it } from "vitest";

import type { NovelDetailResponse } from "@/entities/novel";

import {
  nodeKeyToSelection,
  parseBoardSelection,
  resolveBoardSelection,
  toBoardSelectValue,
  toSelectedNodeKey,
} from "./boardSelection";
import { BATCH_GAP, EPISODE_GAP, EPISODE_NODE_HEIGHT } from "./boardNode";
import { toEpisodeBatchCopy } from "./episodeBatchCopy";
import { toFlowListSections } from "./flowList";
import { layoutBoard } from "./layoutBoard";
import { toBoardModel } from "./toBoardModel";

const KEY = "0f8b2c1e-1d2e-4f3a-9b8c-7d6e5f4a3b2c";

describe("화 k 화면 주소(`plan:{화 키}`)", () => {
  it("읽고 쓴다", () => {
    expect(parseBoardSelection(`plan:${KEY}`)).toEqual({ kind: "planEpisode", key: KEY });
    expect(toBoardSelectValue({ kind: "planEpisode", key: KEY })).toBe(`plan:${KEY}`);
    expect(parseBoardSelection("plan:not-a-key")).toBeUndefined();
  });

  it("스위치가 켜졌거나 아직 모르면 그대로, 꺼졌으면 접는다", () => {
    const selection = { kind: "planEpisode", key: KEY } as const;
    expect(resolveBoardSelection(selection, [], [], { plan: "on" })).toEqual(selection);
    expect(resolveBoardSelection(selection, [], [], { plan: "loading" })).toEqual(selection);
    expect(resolveBoardSelection(selection, [], [], { plan: "off" })).toBeUndefined();
  });

  it("캔버스 노드가 아니다", () => {
    expect(toSelectedNodeKey({ kind: "planEpisode", key: KEY })).toBeUndefined();
    expect(nodeKeyToSelection(`plan:${KEY}`)).toBeUndefined();
  });
});

const novel = {
  chapters: [
    { id: "c1", batchId: "b1", ordinal: 1, title: null, summary: null, charCount: 1, finishedReading: false, episodeOutlineId: null },
    { id: "c2", batchId: "b1", ordinal: 2, title: null, summary: null, charCount: 1, finishedReading: false, episodeOutlineId: null },
    { id: "c3", batchId: "b2", ordinal: 3, title: null, summary: null, charCount: 1, finishedReading: false, episodeOutlineId: "eo-3" },
    { id: "c4", batchId: "b3", ordinal: 4, title: null, summary: null, charCount: 1, finishedReading: false, episodeOutlineId: "eo-4" },
  ],
  batches: [
    { id: "b1", ordinal: 1 },
    { id: "b2", ordinal: 2 },
    { id: "b3", ordinal: 3 },
  ],
  settingNotes: "",
  pendingAiEdits: [],
  pendingBlockEdits: [],
  activeJob: null,
} as unknown as NovelDetailResponse;

describe("구성 흐름 묶음의 틀", () => {
  const model = toBoardModel(novel, []);

  it("구성 흐름 묶음에는 표지를 단다", () => {
    expect(model.batches.map((batch) => batch.isOutlineFlow === true)).toEqual([false, true, true]);
  });

  it("캔버스 틀은 옛 묶음에만 그린다", () => {
    const frames = layoutBoard(model, null).nodes.filter((node) => node.type === "batchFrame");
    expect(frames.map((frame) => frame.id)).toEqual(["batch:b1"]);
  });

  it("이어진 구성안 화 사이는 같은 묶음 간격이다", () => {
    const episodes = layoutBoard(model, null).nodes.filter((node) => node.type === "episode");
    const y = episodes.map((node) => node.position.y);
    expect(y[1]! - y[0]!).toBe(EPISODE_NODE_HEIGHT + EPISODE_GAP);
    expect(y[2]! - y[1]!).toBe(EPISODE_NODE_HEIGHT + BATCH_GAP);
    expect(y[3]! - y[2]!).toBe(EPISODE_NODE_HEIGHT + EPISODE_GAP);
  });

  it("좁은 목록은 이어진 구성안 화를 한 덩어리로 모은다", () => {
    expect(toFlowListSections(model).map(({ label, episodes }) => ({ label, ids: episodes.map((e) => e.episodeId) }))).toEqual([
      { label: "묶음 1 · 1~2화", ids: ["c1", "c2"] },
      { label: "구성안으로 쓴 화 · 3~4화", ids: ["c3", "c4"] },
    ]);
  });
});

describe("화 패널의 묶음 자리 문장", () => {
  it("옛 화는 그대로다", () => {
    expect(toEpisodeBatchCopy({ isOutlineFlow: false, batchOrdinal: 2, rangeLabel: "3~5화", episodeCount: 3 })).toEqual({
      heading: "묶음 2 · 3~5화",
      note: "한 번에 만든 화들이라 다시 만들거나 지울 때 함께 바뀌어요. 고친 화 제목은 다시 만들어도 그대로예요.",
      notLastHint: "지우기는 마지막 묶음만 할 수 있어요.",
    });
    expect(toEpisodeBatchCopy({ isOutlineFlow: false, batchOrdinal: undefined, rangeLabel: "3화", episodeCount: 1 })).toEqual({
      heading: "3화",
      note: "다시 만들어도 고친 화 제목은 그대로예요.",
      notLastHint: "지우기는 마지막 묶음만 할 수 있어요.",
    });
  });

  it("구성안으로 쓴 화는 묶음 대신 화를 말한다", () => {
    expect(toEpisodeBatchCopy({ isOutlineFlow: true, batchOrdinal: 4, rangeLabel: "4화", episodeCount: 1 })).toEqual({
      heading: "구성안으로 쓴 화 · 4화",
      note: "같은 장면 구성안으로 다시 써요. 고친 화 제목은 다시 만들어도 그대로예요.",
      notLastHint: "지우기는 마지막 화만 할 수 있어요.",
    });
  });
});
