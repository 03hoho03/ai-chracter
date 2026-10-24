// 구성 흐름 스위치가 꺼진 동안 보드 작업 줄이 보이는 옛 작업(새 화·다시 만들기·남은 대화 한 번에)의 진행·결과·실패·막힘 문장.
// 구성안 작업의 문구를 더해도 이 상태들은 지금까지와 글자 하나까지 같아야 한다.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { NovelChapterJobFlow } from "@/features/create-novel-chapter";

import { NovelBoardJobLine } from "./NovelBoardJobLine";

const idleFlow = {
  statusId: "status",
  preparing: undefined,
  isJobRunning: false,
  isAiEditRunning: false,
  isRoomGone: false,
  isBusy: false,
  hasPollError: false,
  runningKind: undefined,
  runningRangeLabel: undefined,
  chainProgress: undefined,
  notice: undefined,
  startCreate: () => Promise.resolve(),
  startRegenerate: () => Promise.resolve(),
  retry: () => {},
} as unknown as NovelChapterJobFlow;

function render(flow: Partial<Record<keyof NovelChapterJobFlow, unknown>>): string {
  return renderToStaticMarkup(
    createElement(NovelBoardJobLine, {
      flow: { ...idleFlow, ...flow } as unknown as NovelChapterJobFlow,
      blockedReasonId: "blocked",
      heldChapter: undefined,
      onOpenHeldChapter: () => {},
      createButtonRef: { current: null },
    }),
  );
}

describe("구성 흐름 스위치 꺼짐 — 보드 작업 줄", () => {
  it("아무 일도 없을 때", () => {
    expect(render({})).toMatchSnapshot();
  });

  it("새 화를 쓰는 중", () => {
    expect(render({ isJobRunning: true, isBusy: true, runningKind: "chapter_generate" })).toMatchSnapshot();
  });

  it("묶음을 다시 쓰는 중", () => {
    expect(
      render({ isJobRunning: true, isBusy: true, runningKind: "chapter_regenerate", runningRangeLabel: "3~5화" }),
    ).toMatchSnapshot();
  });

  it("남은 대화 한 번에 진행 중", () => {
    expect(
      render({ isJobRunning: true, isBusy: true, runningKind: "chain_generate", chainProgress: { completed: 1, planned: 3 } }),
    ).toMatchSnapshot();
  });

  it("진행 상황을 못 받는 중", () => {
    expect(render({ isJobRunning: true, isBusy: true, runningKind: "chapter_generate", hasPollError: true })).toMatchSnapshot();
  });

  it("끝난 결과", () => {
    expect(render({ notice: { tone: "done", message: "3화를 만들었어요." } })).toMatchSnapshot();
  });

  it("다시 시도할 수 있는 실패", () => {
    expect(
      render({ notice: { tone: "error", message: "새 화를 만들지 못했어요.", retry: { kind: "generate" } } }),
    ).toMatchSnapshot();
  });

  it("방 없음", () => {
    expect(render({ isRoomGone: true })).toMatchSnapshot();
  });

  it("AI 수정 중", () => {
    expect(render({ isAiEditRunning: true, isBusy: true })).toMatchSnapshot();
  });
});
