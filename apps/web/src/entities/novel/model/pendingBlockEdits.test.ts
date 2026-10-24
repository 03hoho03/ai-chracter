import { describe, expect, it } from "vitest";

import {
  hasPendingBlockEdits,
  hasPendingEdits,
  isBlockEditJob,
  toPendingBlockEdits,
  withSettledPatches,
  withStalePatches,
  type NovelBlockEditPatch,
  type NovelPendingBlockEdit,
} from "./pendingBlockEdits";

function patch(id: string, blockId: string, extra: Partial<NovelBlockEditPatch> = {}): NovelBlockEditPatch {
  return { id, blockId, state: "pending", paragraphs: [`${id} 수정안`], fresh: true, ...extra };
}

function job(id: string, chapterId: string, patches: NovelBlockEditPatch[], bundles: NovelPendingBlockEdit["bundles"] = []) {
  return { id, chapterId, instruction: "짧게", patches, bundles, createdAt: "2026-10-24T00:00:00Z" } satisfies NovelPendingBlockEdit;
}

const oldEdit = {
  id: "old",
  chapterId: "c2",
  paragraphStart: 0,
  paragraphEnd: 0,
  instruction: "",
  resultText: "",
  createdAt: "2026-10-24T00:00:00Z",
};

describe("toPendingBlockEdits", () => {
  // 생성 타입에서 칸이 선택이다 — 옛 응답·시험 픽스처에는 칸이 없다.
  it("칸이 없으면 빈 목록이다", () => {
    expect(toPendingBlockEdits({})).toEqual([]);
  });

  it("그 화의 작업만, 대기 수정안이 남은 작업만 돌려준다", () => {
    const here = job("j1", "c1", [patch("p1", "b1")]);
    const settled = job("j2", "c1", [patch("p2", "b2", { state: "applied", paragraphs: null })]);
    const other = job("j3", "c2", [patch("p3", "b3")]);
    expect(toPendingBlockEdits({ pendingBlockEdits: [here, settled, other] }, "c1")).toEqual([here]);
    expect(toPendingBlockEdits({ pendingBlockEdits: [here, settled, other] }).map((edit) => edit.id)).toEqual(["j1", "j3"]);
  });

  // 블록이 바뀌어 지금은 쓸 수 없는 대기 수정안도 버리기를 기다린다.
  it("쓸 수 없게 된 대기 수정안만 남은 작업도 돌려준다", () => {
    const stale = job("j1", "c1", [patch("p1", "b1", { fresh: false })]);
    expect(toPendingBlockEdits({ pendingBlockEdits: [stale] }, "c1")).toEqual([stale]);
  });
});

describe("hasPendingEdits", () => {
  const novel = {
    pendingAiEdits: [oldEdit],
    pendingBlockEdits: [job("j1", "c1", [patch("p1", "b1")])],
  };

  it("옛 수정안이나 여러 문단 수정안이 그 화들에 있으면 참이다", () => {
    expect(hasPendingEdits(novel, new Set(["c1"]))).toBe(true);
    expect(hasPendingEdits(novel, new Set(["c2"]))).toBe(true);
    expect(hasPendingEdits(novel, new Set(["c3"]))).toBe(false);
  });

  it("여러 문단 수정안만 따로 물을 수 있다", () => {
    expect(hasPendingBlockEdits(novel, new Set(["c1"]))).toBe(true);
    expect(hasPendingBlockEdits(novel, new Set(["c2"]))).toBe(false);
  });

  it("여러 문단 수정 칸이 없는 상세도 옛 수정안으로 판정한다", () => {
    expect(hasPendingEdits({ pendingAiEdits: [oldEdit] }, new Set(["c2"]))).toBe(true);
    expect(hasPendingEdits({ pendingAiEdits: [] }, new Set(["c2"]))).toBe(false);
  });
});

describe("withSettledPatches", () => {
  const edits = [
    job("j1", "c1", [patch("p1", "b1"), patch("p2", "b2"), patch("p3", "b3", { state: "stale", paragraphs: null })], [
      { id: "u1", patchIds: ["p2", "p3"], reason: "이어진 대사" },
    ]),
    job("j2", "c1", [patch("p4", "b4")]),
  ];

  it("적용한 단위의 수정안만 상태를 바꾸고 문단을 비운다 — 같은 작업의 남은 수정안과 다른 작업은 그대로다", () => {
    const next = withSettledPatches(edits, "j1", ["p1"], "applied");
    expect(next?.[0]?.patches.map((item) => [item.id, item.state, item.paragraphs])).toEqual([
      ["p1", "applied", null],
      ["p2", "pending", ["p2 수정안"]],
      ["p3", "stale", null],
    ]);
    expect(next?.[1]).toEqual(edits[1]);
  });

  it("모두 버리기는 대기·낡음 수정안을 버림으로 바꾸고, 대기가 없어진 작업은 목록에서 빠진다", () => {
    const next = withSettledPatches(edits, "j1", "all", "dismissed");
    expect(next?.map((edit) => edit.id)).toEqual(["j2"]);
  });

  it("칸이 없던 상세는 그대로 둔다", () => {
    expect(withSettledPatches(undefined, "j1", "all", "dismissed")).toBeUndefined();
  });
});

describe("withStalePatches", () => {
  it("거절된 수정안만 지금 쓸 수 없음으로 바꾼다", () => {
    const edits = [job("j1", "c1", [patch("p1", "b1"), patch("p2", "b2")])];
    const next = withStalePatches(edits, ["p2"]);
    expect(next?.[0]?.patches.map((item) => [item.id, item.fresh])).toEqual([
      ["p1", true],
      ["p2", false],
    ]);
  });
});

describe("isBlockEditJob", () => {
  const range = { baseRevisionId: "r1", paragraphStart: 0, paragraphEnd: 1, instruction: null, resultText: null };

  // 여러 문단 수정 작업은 서버가 문단 범위 칸을 늘 비운다 — 옛 연속 범위 수정은 늘 채운다.
  it("AI 수정 작업에서 문단 범위가 비었으면 여러 문단 수정이다", () => {
    expect(isBlockEditJob({ kind: "ai_edit", aiEdit: { ...range, paragraphStart: null, paragraphEnd: null } })).toBe(true);
  });

  it("옛 연속 범위 수정·다른 작업·칸 없음은 아니다", () => {
    expect(isBlockEditJob({ kind: "ai_edit", aiEdit: range })).toBe(false);
    expect(isBlockEditJob({ kind: "ai_edit", aiEdit: null })).toBe(false);
    expect(isBlockEditJob({ kind: "chapter_generate", aiEdit: null })).toBe(false);
  });
});
