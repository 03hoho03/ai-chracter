import { describe, expect, it } from "vitest";

import type { NovelBlockEditPatch, NovelPendingBlockEdit } from "@/entities/novel";

import { countFreshPatches, countFreshPatchesInBlocks, toPatchLayout } from "./blockEditPatches";

const BLOCKS = ["b0", "b1", "b2", "b3", "b4", "b5"];

function patch(id: string, blockId: string, extra: Partial<NovelBlockEditPatch> = {}): NovelBlockEditPatch {
  return { id, blockId, state: "pending", paragraphs: [`${id} 수정안`], fresh: true, ...extra };
}

function job(id: string, patches: NovelBlockEditPatch[], bundles: NovelPendingBlockEdit["bundles"] = []): NovelPendingBlockEdit {
  return { id, chapterId: "c1", instruction: `${id} 요청`, patches, bundles, createdAt: "2026-10-24T00:00:00Z" };
}

/** 시안의 예: 2(b1)는 독립 수정안, 4+5(b3·b4)는 묶음이고 5는 사용자가 고쳐 지금 쓸 수 없다. */
const mockup = job(
  "j1",
  [patch("p1", "b1"), patch("p3", "b3"), patch("p4", "b4", { fresh: false })],
  [{ id: "u1", patchIds: ["p3", "p4"], reason: "5가 4의 대사를 받아요" }],
);

describe("toPatchLayout", () => {
  it("수정안은 그 블록 자리에 놓인다", () => {
    const layout = toPatchLayout([mockup], BLOCKS);
    expect([...layout.cardsAt.keys()].sort((a, b) => a - b)).toEqual([1, 3, 4]);
    expect(layout.cardBlockIndexes).toEqual(new Set([1, 3, 4]));
  });

  it("묶음에 들지 않은 수정안만 자기 적용·버리기를 갖는다", () => {
    const layout = toPatchLayout([mockup], BLOCKS);
    expect(layout.cardsAt.get(1)?.[0]?.unit?.request).toEqual({ patchId: "p1" });
    expect(layout.cardsAt.get(3)?.[0]?.unit).toBeUndefined();
    expect(layout.cardsAt.get(3)?.[0]?.bundleId).toBe("u1");
  });

  it("묶음의 적용·버리기는 마지막 원소 뒤에 한 번 서고, 쓸 수 없는 원소가 있으면 함께 적용할 수 없다", () => {
    const layout = toPatchLayout([mockup], BLOCKS);
    const [bundle] = layout.bundlesAfter.get(4) ?? [];
    expect(bundle?.request).toEqual({ bundleId: "u1" });
    expect(bundle?.indexes).toEqual([3, 4]);
    expect(bundle?.reason).toBe("5가 4의 대사를 받아요");
    expect(bundle?.isApplicable).toBe(false);
    expect(layout.bundlesAfter.size).toBe(1);
  });

  it("작업의 모두 버리기는 그 작업의 마지막 수정안 뒤에 선다", () => {
    const layout = toPatchLayout([mockup], BLOCKS);
    expect(layout.jobsAfter.get(4)?.map((item) => item.jobId)).toEqual(["j1"]);
    expect(layout.jobsAfter.get(4)?.[0]?.instruction).toBe("j1 요청");
  });

  it("카드는 지금 쓸 수 있는지를 든다", () => {
    const layout = toPatchLayout([mockup], BLOCKS);
    expect(layout.cardsAt.get(1)?.[0]?.isApplicable).toBe(true);
    expect(layout.cardsAt.get(4)?.[0]?.isApplicable).toBe(false);
  });

  it("적용·버린 수정안은 그리지 않고, 대기 원소가 없는 묶음도 그리지 않는다", () => {
    const edit = job(
      "j1",
      [
        patch("p1", "b1", { state: "applied", paragraphs: null }),
        patch("p2", "b2"),
        patch("p3", "b3", { state: "dismissed", paragraphs: null }),
        patch("p4", "b4", { state: "stale", paragraphs: null }),
      ],
      [{ id: "u1", patchIds: ["p3", "p4"], reason: null }],
    );
    const layout = toPatchLayout([edit], BLOCKS);
    expect([...layout.cardsAt.keys()].sort((a, b) => a - b)).toEqual([2]);
    expect(layout.bundlesAfter.size).toBe(0);
  });

  // 서버가 이미 낡음으로 바꾼 독립 수정안도 버리기를 기다린다 — 왜 사라졌는지 자리에서 보인다.
  it("낡음으로 바뀐 독립 수정안은 그 자리에 버리기만 있는 카드로 남는다", () => {
    const layout = toPatchLayout([job("j1", [patch("p1", "b1"), patch("p2", "b2", { state: "stale", paragraphs: null })])], BLOCKS);
    const [card] = layout.cardsAt.get(2) ?? [];
    expect(card?.isApplicable).toBe(false);
    expect(card?.unit?.request).toEqual({ patchId: "p2" });
  });

  it("블록이 지금 판에 없는 수정안은 자리 대신 작업 끝에서 센다", () => {
    const layout = toPatchLayout([job("j1", [patch("p1", "b1"), patch("p2", "gone", { fresh: false })])], BLOCKS);
    expect([...layout.cardsAt.keys()].sort((a, b) => a - b)).toEqual([1]);
    expect(layout.jobsAfter.get(1)?.[0]?.unplacedUnits.map((unit) => unit.request)).toEqual([{ patchId: "p2" }]);
  });

  it("자리가 하나도 없는 작업은 화 끝에 선다", () => {
    const layout = toPatchLayout([job("j1", [patch("p1", "gone", { fresh: false })])], BLOCKS);
    expect(layout.jobsAfter.get(BLOCKS.length - 1)?.map((item) => item.jobId)).toEqual(["j1"]);
  });

  it("작업이 여럿이면 각자 자기 마지막 자리 뒤에 선다", () => {
    const layout = toPatchLayout([job("j1", [patch("p1", "b4")]), job("j2", [patch("p2", "b0")])], BLOCKS);
    expect(layout.jobsAfter.get(4)?.map((item) => item.jobId)).toEqual(["j1"]);
    expect(layout.jobsAfter.get(0)?.map((item) => item.jobId)).toEqual(["j2"]);
  });
});

describe("countFreshPatches", () => {
  it("지금 쓸 수 있는 대기 수정안만 센다", () => {
    expect(countFreshPatches(mockup)).toBe(2);
  });

  it("고르는 블록에 놓인 것만 셀 수 있다", () => {
    expect(countFreshPatchesInBlocks([mockup], new Set(["b1", "b4"]))).toBe(1);
    expect(countFreshPatchesInBlocks([mockup], new Set(["b0"]))).toBe(0);
  });
});

// 다시 검사는 서버가 물을 거리가 있을 때만 받는다 — 고친 원소가 지금 판에 있고(지워졌으면 보여 줄 글이 없다), 따로 적용할 남은
// 원소가 있어야 한다. 그 밖이면 버튼이 없다(누르면 409 뿐이다).
describe("toPatchLayout — 묶음 다시 검사", () => {
  function bundleOf(edit: NovelPendingBlockEdit) {
    return [...toPatchLayout([edit], BLOCKS).bundlesAfter.values()].flat()[0];
  }

  it("고친 원소와 쓸 수 있는 원소가 함께 있는 묶음은 다시 검사할 수 있다", () => {
    expect(bundleOf(mockup)?.canRecheck).toBe(true);
  });

  it("서버가 낡음으로 바꾼 원소도 고친 원소다", () => {
    const edit = job(
      "j1",
      [patch("p3", "b3"), patch("p4", "b4", { state: "stale", paragraphs: null, fresh: false })],
      [{ id: "u1", patchIds: ["p3", "p4"], reason: null }],
    );
    expect(bundleOf(edit)?.canRecheck).toBe(true);
  });

  it("원소가 모두 쓸 수 있으면 다시 검사할 것이 없다(함께 적용하면 된다)", () => {
    const edit = job("j1", [patch("p3", "b3"), patch("p4", "b4")], [{ id: "u1", patchIds: ["p3", "p4"], reason: null }]);
    expect(bundleOf(edit)?.canRecheck).toBe(false);
  });

  it("고친 원소의 문단이 지워졌으면 다시 검사할 수 없다", () => {
    const edit = job(
      "j1",
      [patch("p3", "b3"), patch("p4", "gone", { fresh: false })],
      [{ id: "u1", patchIds: ["p3", "p4"], reason: null }],
    );
    expect(bundleOf(edit)?.canRecheck).toBe(false);
  });

  it("쓸 수 있는 원소가 없으면 다시 검사할 수 없다", () => {
    const edit = job(
      "j1",
      [patch("p3", "b3", { fresh: false }), patch("p4", "b4", { fresh: false })],
      [{ id: "u1", patchIds: ["p3", "p4"], reason: null }],
    );
    expect(bundleOf(edit)?.canRecheck).toBe(false);
  });

  it("묶음에 들지 않은 수정안은 다시 검사하지 않는다", () => {
    const layout = toPatchLayout([job("j1", [patch("p1", "b1", { fresh: false })])], BLOCKS);
    expect(layout.cardsAt.get(1)?.[0]?.unit?.canRecheck).toBe(false);
  });
});
