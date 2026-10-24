// 대화로 바로 만든 화(옛 흐름 화)만 있는 소설의 보드 — 보드 모델, 자동 배치와 묶음 틀, 좁은 화면 목록의 덩어리. 구성안으로 쓴
// 화의 묶음 틀을 바꿔도 이 소설들의 보드는 지금까지와 같아야 한다. 스위치가 꺼졌으면 구성 모드 주소도 접힌다.
import { describe, expect, it } from "vitest";

import type { NovelDetailResponse } from "@/entities/novel";

import { parseBoardSelection, resolveBoardSelection } from "./boardSelection";
import { toFlowListSections } from "./flowList";
import { layoutBoard } from "./layoutBoard";
import { toBoardModel } from "./toBoardModel";

const novel = {
  chapters: [
    { id: "c1", batchId: "b1", ordinal: 1, title: "첫 밤", summary: null, charCount: 4812, finishedReading: false, episodeOutlineId: null },
    { id: "c2", batchId: "b2", ordinal: 2, title: null, summary: "요약", charCount: 5120, finishedReading: true, episodeOutlineId: null },
    { id: "c3", batchId: "b2", ordinal: 3, title: null, summary: null, charCount: 300, finishedReading: false, episodeOutlineId: null },
  ],
  batches: [
    { id: "b1", ordinal: 1 },
    { id: "b2", ordinal: 2 },
  ],
  settingNotes: "",
  pendingAiEdits: [],
  pendingBlockEdits: [],
  activeJob: null,
} as unknown as NovelDetailResponse;

describe("옛 흐름 화만 있는 보드", () => {
  const model = toBoardModel(novel, []);

  it("보드 모델", () => {
    expect(model).toMatchSnapshot();
  });

  it("자동 배치와 묶음 틀", () => {
    const { nodes } = layoutBoard(model, null);
    expect(nodes.map(({ id, type, position, width, height }) => ({ id, type, position, width, height }))).toMatchSnapshot();
  });

  it("좁은 화면 목록의 덩어리", () => {
    const sections = toFlowListSections(model);
    expect(sections.map(({ key, label, episodes }) => ({ key, label, ids: episodes.map((episode) => episode.episodeId) }))).toMatchSnapshot();
  });
});

describe("구성 흐름 스위치 꺼짐 — 구성 모드 주소", () => {
  it.each(["plan", "plan:0f8b2c1e-1d2e-4f3a-9b8c-7d6e5f4a3b2c"])("%s 는 고른 것 없음으로 접힌다", (value) => {
    expect(resolveBoardSelection(parseBoardSelection(value), [], [], { plan: "off" })).toBeUndefined();
  });
});
