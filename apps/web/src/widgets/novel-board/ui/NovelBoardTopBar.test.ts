import { createMemoryHistory, createRootRoute, createRouter, RouterContextProvider } from "@tanstack/react-router";
import { createElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { NovelChapterJobFlow } from "@/features/create-novel-chapter";

import { isCreateChapterBlocked } from "../model/createChapterGate";

import { NovelBoardTopBar } from "./NovelBoardTopBar";

const router = createRouter({
  routeTree: createRootRoute(),
  history: createMemoryHistory({ initialEntries: ["/"] }),
});

function inRouter(node: ReactNode): string {
  return renderToStaticMarkup(createElement(RouterContextProvider, { router, children: node }));
}

const idleFlow = {
  statusId: "status",
  preparing: undefined,
  isJobRunning: false,
  isAiEditRunning: false,
  isRoomGone: false,
  isBusy: false,
} as unknown as NovelChapterJobFlow;

// 구성 흐름 스위치는 가격 응답에 실려 온다. 받기 전에 누르면 스위치가 켜졌어도 옛 흐름(경계 고르기)이 시작되므로, 받을 때까지
// "다음 화 만들기"를 막는다.
describe("상단바 다음 화 만들기 — 스위치를 아직 모를 때", () => {
  it("가격 응답 전에는 못 누른다", () => {
    expect(isCreateChapterBlocked(idleFlow, { isSwitchPending: true })).toBe(true);
    expect(isCreateChapterBlocked(idleFlow, { isSwitchPending: false })).toBe(false);
  });

  it("바쁘거나 방이 없으면 지금처럼 못 누른다", () => {
    expect(isCreateChapterBlocked({ ...idleFlow, isBusy: true }, { isSwitchPending: false })).toBe(true);
    expect(isCreateChapterBlocked({ ...idleFlow, isRoomGone: true }, { isSwitchPending: false })).toBe(true);
  });

  it("버튼은 aria-disabled 로 막히고 아이콘이 진행 표시가 된다", () => {
    const markup = inRouter(
      createElement(NovelBoardTopBar, {
        novelId: "novel-1",
        title: "달빛 아래의 계약",
        create: {
          flow: idleFlow,
          hasChapters: true,
          blockedReasonId: undefined,
          buttonRef: { current: null },
          isSwitchPending: true,
        },
      }),
    );
    expect(markup).toContain('aria-label="다음 화 만들기" aria-disabled="true"');
    expect(markup).toContain("animate-spin");
  });
});
