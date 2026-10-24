// 구성 모드의 화 하나에서 유료 버튼(장면 구성안 다시 만들기·원고 쓰기)이 담을 대화의 승인 상태를 따르는가. 서버는 승인한 담을 대화의
// 원문이 바뀌었으면 과금 전에 409 로 막는데, 이 화면에는 바뀐 구간을 보이는 자리가 없어 누를 때마다 같은 거절이 되풀이됐다.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { novelKeys, type NovelDetailResponse } from "@/entities/novel";
import type { NovelChapterJobFlow } from "@/features/create-novel-chapter";

import { NovelPlanEpisodeDocument } from "./NovelPlanEpisodeDocument";

const novel = {
  id: "novel-1",
  chatRoomId: "room-1",
  chapters: [],
  limits: { chapterTitleMaxLength: 60 },
} as unknown as NovelDetailResponse;

const idleFlow = {
  statusId: "status",
  preparing: undefined,
  preparingEpisodeKey: undefined,
  isJobRunning: false,
  isAiEditRunning: false,
  runningKind: undefined,
  runningEpisodeKey: "other",
  startEpisodeOutline: () => Promise.resolve(),
  startOutlineChapter: () => Promise.resolve(),
  reportEpisodeEditing: () => {},
} as unknown as NovelChapterJobFlow;

const outlineView = {
  revision: 1,
  source: "generate",
  model: "gemini",
  approvedAt: "2026-10-24T00:00:00Z",
  createdAt: "2026-10-24T00:00:00Z",
  stale: false,
  sourceSections: null,
  episodes: [
    {
      key: "k1",
      title: "첫 만남",
      summary: "둘이 처음 만난다.",
      goal: "",
      basis: [{ startMessageId: "m1", endMessageId: "m4" }],
      chapterId: null,
      sceneOutline: "approved",
      turnCount: 2,
    },
  ],
};

const sceneView = {
  revision: 1,
  source: "generate",
  model: "gemini",
  approvedAt: "2026-10-24T00:00:00Z",
  createdAt: "2026-10-24T00:00:00Z",
  stale: false,
  scenes: [],
};

function selectionView(sourceChanged: boolean) {
  return {
    revision: 1,
    approvedAt: "2026-10-24T00:00:00Z",
    roomEndMessageId: "m4",
    roomEndMessageCreatedAt: "2026-10-24T00:00:04Z",
    sections: [
      {
        startMessageId: "m1",
        endMessageId: "m4",
        startMessageCreatedAt: "2026-10-24T00:00:01Z",
        endMessageCreatedAt: "2026-10-24T00:00:04Z",
        mode: "include",
        assistantMessageCount: 2,
        sourceChanged,
      },
    ],
  };
}

function render(selection: "ok" | "sourceChanged" | "unapproved" | "loading"): string {
  const client = new QueryClient();
  client.setQueryData(novelKeys.outline(novel.id), { approved: outlineView, draft: null, maxEpisodes: 30, models: [] });
  client.setQueryData(novelKeys.episodeOutline(novel.id, "k1"), {
    episodeKey: "k1",
    approved: sceneView,
    draft: null,
    models: [],
    chapterModels: [],
    chapterId: null,
  });
  if (selection !== "loading") {
    client.setQueryData(novelKeys.sourceSelection(novel.id), {
      approved: selection === "unapproved" ? null : selectionView(selection === "sourceChanged"),
      draft: selection === "unapproved" ? selectionView(false) : null,
      proposal: null,
      lockedRanges: [],
      roomEndMessageId: "m4",
      hasNewMessages: false,
    });
  }
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client },
      createElement(NovelPlanEpisodeDocument, {
        novel,
        episodeKey: "k1",
        chapterFlow: idleFlow,
        headingRef: { current: null },
        onOpenChapter: () => {},
        onDraftDirtyChange: () => {},
      }),
    ),
  );
}

/** 이름이 `label` 인 버튼의 여는 태그. */
function buttonTag(html: string, label: string): string {
  const match = new RegExp(`<button[^>]*>(?:(?!</button>)[\\s\\S])*${label}</button>`).exec(html);
  return /^<button[^>]*>/.exec(match?.[0] ?? "")?.[0] ?? "";
}

describe("구성 모드 화 화면 — 담을 대화 승인 상태", () => {
  it("담을 대화가 그대로면 원고 쓰기·다시 만들기를 누를 수 있다", () => {
    const html = render("ok");
    expect(buttonTag(html, "원고 쓰기")).not.toBe("");
    expect(buttonTag(html, "원고 쓰기")).toContain('aria-disabled="false"');
    expect(buttonTag(html, "다시 만들기")).toContain('aria-disabled="false"');
    expect(html).not.toContain("고른 뒤 바뀌었어요");
  });

  it("승인한 담을 대화의 구간이 고른 뒤 바뀌었으면 둘 다 막고 까닭을 말한다", () => {
    const html = render("sourceChanged");
    expect(buttonTag(html, "원고 쓰기")).toContain('aria-disabled="true"');
    expect(buttonTag(html, "다시 만들기")).toContain('aria-disabled="true"');
    expect(html).toContain("담을 대화의 구간 어딘가가 고른 뒤 바뀌었어요.");
  });

  it("승인한 담을 대화가 없으면 막고 승인하라고 말한다", () => {
    const html = render("unapproved");
    expect(buttonTag(html, "원고 쓰기")).toContain('aria-disabled="true"');
    expect(html).toContain("담을 대화를 먼저 승인해주세요.");
  });

  // 담을 대화를 받는 동안은 모른다 — 서버가 같은 경우를 막으니 화면이 앞서 막지 않는다.
  it("담을 대화를 아직 못 받았으면 막지 않는다", () => {
    expect(buttonTag(render("loading"), "원고 쓰기")).toContain('aria-disabled="false"');
  });
});
