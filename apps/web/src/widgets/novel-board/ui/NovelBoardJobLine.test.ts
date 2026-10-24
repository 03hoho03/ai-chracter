import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { NovelChapterJobFlow } from "@/features/create-novel-chapter";

import { NovelBoardJobLine } from "./NovelBoardJobLine";

function renderRunning(runningKind: string): string {
  const flow = {
    statusId: "status",
    preparing: undefined,
    isJobRunning: true,
    isAiEditRunning: false,
    isRoomGone: false,
    isBusy: true,
    hasPollError: false,
    runningKind,
    runningRangeLabel: undefined,
    chainProgress: undefined,
    notice: undefined,
  } as unknown as NovelChapterJobFlow;
  return renderToStaticMarkup(
    createElement(NovelBoardJobLine, {
      flow,
      blockedReasonId: "blocked",
      heldChapter: undefined,
      onOpenHeldChapter: () => {},
      createButtonRef: { current: null },
    }),
  );
}

// 구성 흐름 작업은 새 화를 쓰는 것이 아니다 — 진행 줄이 그 작업이 무엇을 만드는지 말한다.
describe("보드 작업 줄 — 구성 흐름 작업의 진행 문장", () => {
  it("전체 구성안", () => {
    expect(renderRunning("outline_generate")).toContain("전체 구성안을 만들고 있어요. 이 화면을 떠나도 계속 만들어요.");
  });

  it("장면 구성안", () => {
    expect(renderRunning("episode_outline_generate")).toContain("장면 구성안을 만들고 있어요. 이 화면을 떠나도 계속 만들어요.");
  });

  it("구성안으로 새 화", () => {
    expect(renderRunning("outline_chapter_generate")).toContain("구성안으로 새 화를 쓰고 있어요. 이 화면을 떠나도 계속 써요.");
  });
});
