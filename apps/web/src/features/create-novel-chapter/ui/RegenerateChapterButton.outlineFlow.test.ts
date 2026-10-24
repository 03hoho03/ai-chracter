import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { toRegenerateAction } from "../model/regenerateAction";
import { toRegenerateConfirmDescription } from "../model/regenerateConfirm";
import type { NovelChapterJobFlow } from "../model/useNovelChapterJob";

import { RegenerateChapterButton } from "./RegenerateChapterButton";

const idleFlow = {
  statusId: "status",
  isJobRunning: false,
  isRoomGone: false,
  isBusy: false,
  outlineFlow: "on",
} as unknown as NovelChapterJobFlow;

const oldChapter = { id: "c1", batchId: "b1", ordinal: 1, episodeOutlineId: null };
const outlineChapter = { id: "c2", batchId: "b2", ordinal: 2, episodeOutlineId: "eo-2" };
const chapters = [oldChapter, outlineChapter];

function render(flow: Partial<Record<keyof NovelChapterJobFlow, unknown>>, chapter: typeof oldChapter | typeof outlineChapter) {
  return renderToStaticMarkup(
    createElement(RegenerateChapterButton, {
      flow: { ...idleFlow, ...flow } as unknown as NovelChapterJobFlow,
      chapter,
      chapters,
    }),
  );
}

describe("다시 만들기 갈래", () => {
  it("대화로 바로 만든 화는 묶음 다시 만들기다(스위치와 무관)", () => {
    for (const outlineFlow of ["on", "off", "loading"] as const) {
      expect(toRegenerateAction(oldChapter, outlineFlow)).toEqual({ kind: "batch", batchId: "b1" });
    }
  });

  it("구성안으로 쓴 화는 켜져 있으면 새 라우트, 꺼졌으면 이유와 함께 못 한다, 모르면 이유 없이 기다린다", () => {
    expect(toRegenerateAction(outlineChapter, "on")).toEqual({ kind: "outline", chapterId: "c2" });
    expect(toRegenerateAction(outlineChapter, "off")).toEqual({
      kind: "unavailable",
      reason: "구성 흐름이 꺼져 있어 지금은 다시 만들 수 없어요.",
    });
    expect(toRegenerateAction(outlineChapter, "loading")).toEqual({ kind: "unavailable", reason: undefined });
  });
});

describe("구성안으로 쓴 화의 다시 만들기 버튼", () => {
  it("켜져 있으면 누를 수 있는 한 화 버튼이다", () => {
    const html = render({}, outlineChapter);
    expect(html).toContain('aria-disabled="false"');
    expect(html).toContain("이 화 다시 만들기");
  });

  it("꺼졌으면 aria-disabled 이고 이유 줄을 가리킨다", () => {
    const html = render({ outlineFlow: "off" }, outlineChapter);
    expect(html).toContain('aria-disabled="true"');
    expect(html).toContain("구성 흐름이 꺼져 있어 지금은 다시 만들 수 없어요.");
    const describedBy = /aria-describedby="([^"]+)"/.exec(html)?.[1];
    expect(describedBy).toBeDefined();
    expect(html).toContain(`id="${describedBy}"`);
  });

  it("작업이 도는 중이면 작업 줄을 가리킨다", () => {
    const html = render({ isJobRunning: true, isBusy: true }, outlineChapter);
    expect(html).toContain('aria-disabled="true"');
    expect(html).toContain('aria-describedby="status"');
  });
});

describe("구성안으로 쓴 화의 다시 만들기 확인 설명", () => {
  it("같은 장면 구성안으로 다시 쓴다고 말한다", () => {
    expect(
      toRegenerateConfirmDescription({ rangeLabel: "2화", episodeCount: 1, hasPendingAiEdits: true, isOutlineFlow: true }),
    ).toBe("같은 장면 구성안으로 이 화를 새로 써요. 지금 글은 이력에 남아요. 다시 만들면 이 화에서 적용하지 않은 AI 수정안은 사라지고, 쓴 클로버는 돌아오지 않아요.");
  });
});
