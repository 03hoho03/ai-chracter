// 장면 경계가 있는 화와 묶음 다시 검사. 장면 머리줄과 다시 검사는 여러 문단 수정 스위치가 켜졌을 때만 있고, 꺼졌으면 남은 수정안이
// 있는 화도 지금까지와 글자 하나까지 같다.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { NovelChapterResponse, NovelDetailResponse, NovelPendingBlockEdit } from "@/entities/novel";

import { NovelChapterText } from "./NovelChapterText";

const PARAGRAPHS = [
  "문을 두드렸다.",
  "들어오라는 목소리가 들렸다.",
  "그는 문고리를 잡았다.",
  "회랑은 길고 어두웠다.",
  "발소리가 울렸다.",
  "끝에 창이 하나 있었다.",
];

function chapterWith(scenes: NovelChapterResponse["revision"]["scenes"]): NovelChapterResponse {
  return {
    id: "chapter-1",
    novelId: "novel-1",
    ordinal: 2,
    assistantMessageCount: 4,
    revision: {
      id: "r1",
      revisionNo: 3,
      source: "generate",
      revertedFromRevisionId: null,
      createdAt: "2026-10-24T00:00:00Z",
      body: PARAGRAPHS.join("\n\n"),
      paragraphs: PARAGRAPHS,
      blocks: PARAGRAPHS.map((text, index) => ({ id: `b${index}`, text })),
      illustrations: [],
      unplacedIllustrations: [],
      scenes,
    },
  };
}

const TWO_SCENES = [
  { id: "s1", title: "문 앞", blockIds: ["b0", "b1", "b2"] },
  { id: "s2", title: "회랑", blockIds: ["b3", "b4", "b5"] },
];

/** 첫 장면의 묶음(b0+b2) — b2 를 사용자가 고쳐 b0 만 지금 쓸 수 있다. */
const bundleJob: NovelPendingBlockEdit = {
  id: "job-1",
  chapterId: "chapter-1",
  instruction: "문 앞 장면의 긴장을 높여 주세요",
  patches: [
    { id: "p0", blockId: "b0", state: "pending", paragraphs: ["문을 세게 두드렸다."], fresh: true },
    { id: "p2", blockId: "b2", state: "stale", paragraphs: null, fresh: false },
  ],
  bundles: [{ id: "u1", patchIds: ["p0", "p2"], reason: "3번째가 1번째의 소리를 받아요" }],
  createdAt: "2026-10-24T00:00:00Z",
};

/** 둘째 장면의 독립 수정안 둘. */
const sceneTwoJob: NovelPendingBlockEdit = {
  id: "job-2",
  chapterId: "chapter-1",
  instruction: "회랑 묘사를 더해 주세요",
  patches: [
    { id: "q3", blockId: "b3", state: "pending", paragraphs: ["회랑은 끝이 보이지 않았다."], fresh: true },
    { id: "q5", blockId: "b5", state: "pending", paragraphs: ["끝에 달빛이 든 창이 있었다."], fresh: true },
  ],
  bundles: [],
  createdAt: "2026-10-24T00:01:00Z",
};

function novelWith(pendingBlockEdits: NovelPendingBlockEdit[]): NovelDetailResponse {
  return {
    id: "novel-1",
    chapters: [{ id: "chapter-1", batchId: "batch-1", ordinal: 2 }],
    pendingAiEdits: [],
    pendingBlockEdits,
    activeJob: null,
    limits: { chapterBodyMaxLength: 20000, blockEditMaxBlocks: 20 },
  } as unknown as NovelDetailResponse;
}

const aiEdit = {
  statusId: "status",
  isPreparing: false,
  isRunning: false,
  isBlocked: false,
  isOtherJobRunning: false,
  hasPollError: false,
  runningChapterOrdinal: undefined,
  notice: undefined,
  actingEditId: undefined,
  start: () => Promise.resolve(false),
  apply: () => Promise.resolve(),
  dismiss: () => Promise.resolve(),
  report: () => {},
} as unknown as ComponentProps<typeof NovelChapterText>["aiEdit"];

function render({
  novel,
  chapter,
  isFixMode,
  isMultiBlockEditOn,
}: {
  novel: NovelDetailResponse;
  chapter: NovelChapterResponse;
  isFixMode: boolean;
  isMultiBlockEditOn: boolean;
}): string {
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: new QueryClient() },
      createElement(NovelChapterText, {
        novel,
        chapter,
        isFixMode,
        aiEdit,
        onFocusFallback: () => {},
        onDraftDirtyChange: () => {},
        isIllustrationsOn: false,
        onFixModeRequest: () => {},
        onPickImage: () => Promise.resolve(undefined),
        isRevisionRefreshing: false,
        isMultiBlockEditOn,
      }),
    ),
  );
}

describe("NovelChapterText 스위치 꺼짐 — 장면·남은 수정안이 있는 화", () => {
  // 스냅숏은 장면 머리줄·다시 검사를 더하기 전 코드로 찍었다 — 스위치가 꺼진 화면은 그때와 글자 하나까지 같다.
  it.each([
    [true, "작업 하나", [bundleJob]],
    [false, "작업 하나", [bundleJob]],
    [true, "작업 둘", [bundleJob, sceneTwoJob]],
    [false, "작업 둘", [bundleJob, sceneTwoJob]],
  ])("고치기 모드(%s)·%s 화면이 장면 머리줄·다시 검사 전과 같다", (isFixMode, _label, jobs) => {
    const markup = render({
      novel: novelWith(jobs),
      chapter: chapterWith(TWO_SCENES),
      isFixMode,
      isMultiBlockEditOn: false,
    });
    expect(markup).toMatchSnapshot();
  });
});
