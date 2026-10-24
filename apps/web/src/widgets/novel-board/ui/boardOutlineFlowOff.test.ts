// 구성 흐름 스위치가 꺼진 동안의 보드 개요 패널·좁은 화면 목록·상단바. 구성 화면 입구는 스위치가 켜졌을 때만 생기고, 꺼졌으면
// 이 셋이 지금까지와 글자 하나까지 같다.
import { createMemoryHistory, createRootRoute, createRouter, RouterContextProvider } from "@tanstack/react-router";
import { createElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { NovelDetailResponse } from "@/entities/novel";
import type { NovelChapterJobFlow } from "@/features/create-novel-chapter";

import { testBatch, testEpisode, testModel } from "../model/boardTestModel";

import { BoardOverviewPanel } from "./BoardOverviewPanel";
import { NovelBoardTopBar } from "./NovelBoardTopBar";
import { NovelFlowList } from "./NovelFlowList";

const router = createRouter({
  routeTree: createRootRoute(),
  history: createMemoryHistory({ initialEntries: ["/"] }),
});

function inRouter(node: ReactNode): string {
  return renderToStaticMarkup(createElement(RouterContextProvider, { router, children: node }));
}

const novel = {
  id: "novel-1",
  title: "달빛 아래의 계약",
  chatRoomId: "room-1",
  chapters: [
    { id: "chapter-1", batchId: "batch-1", ordinal: 1, readState: { kind: "unread" } },
    { id: "chapter-2", batchId: "batch-2", ordinal: 2, readState: { kind: "unread" } },
  ],
  batches: [{ id: "batch-1" }, { id: "batch-2" }],
} as unknown as NovelDetailResponse;

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

describe("구성 흐름 스위치 꺼짐 — 보드 입구 화면", () => {
  it("넓은 화면 개요 패널", () => {
    expect(
      inRouter(createElement(BoardOverviewPanel, { novel, characterCount: 3, headingRef: { current: null } })),
    ).toMatchSnapshot();
  });

  it("좁은 화면 목록", () => {
    const model = testModel({
      batches: [testBatch("batch-1", 1), testBatch("batch-2", 2)],
      episodes: [testEpisode("chapter-1", "batch-1", 1), testEpisode("chapter-2", "batch-2", 2)],
    });
    expect(
      renderToStaticMarkup(
        createElement(NovelFlowList, { model, characterStatus: "ready", onRetryCharacters: () => {}, onSelect: () => {} }),
      ),
    ).toMatchSnapshot();
  });

  it("상단바(다음 화 만들기)", () => {
    expect(
      inRouter(
        createElement(NovelBoardTopBar, {
          novelId: novel.id,
          title: "달빛 아래의 계약",
          versions: { isOpen: false, onToggle: () => {} },
          create: { flow: idleFlow, hasChapters: true, blockedReasonId: undefined, buttonRef: { current: null } },
        }),
      ),
    ).toMatchSnapshot();
  });
});
