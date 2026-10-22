// 보드 화 본문이 삽화 스위치에 따라 무엇을 그리는가. 판정 함수 하나가 꺼짐을 말하면, 응답에 그림이 실려 와도(켜졌다 꺼진
// 직후처럼) 삽화 조작·위치 확인 필요 목록이 하나도 없어야 한다. 그림 자체는 응답이 정한다.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { NovelChapterResponse, NovelDetailResponse } from "@/entities/novel";

import type { BoardIllustration } from "../model/boardIllustrations";
import { NovelChapterText } from "./NovelChapterText";

function illustration(id: string, overrides: Partial<BoardIllustration>): BoardIllustration {
  return {
    id,
    anchorBlockId: "b0",
    placement: "after",
    order: 0,
    assetId: `asset-${id}`,
    source: "upload",
    url: `https://img.example/${id}.webp`,
    width: 300,
    height: 400,
    withheld: null,
    withheldReason: null,
    ...overrides,
  };
}

const chapter = {
  id: "chapter-1",
  novelId: "novel-1",
  ordinal: 1,
  assistantMessageCount: 4,
  revision: {
    id: "r1",
    revisionNo: 2,
    source: "illustration",
    revertedFromRevisionId: null,
    createdAt: "2026-10-23T00:00:00Z",
    body: "첫 문단\n\n둘째 문단",
    paragraphs: ["첫 문단", "둘째 문단"],
    blocks: [
      { id: "b0", text: "첫 문단" },
      { id: "b1", text: "둘째 문단" },
    ],
    illustrations: [illustration("placed", { anchorBlockId: "b0", placement: "after" })],
    unplacedIllustrations: [illustration("lost", { anchorBlockId: null, placement: null })],
  },
} satisfies NovelChapterResponse;

// 본문이 읽는 칸만 채운 상세 — 나머지 칸은 이 화면이 읽지 않는다.
const novel = {
  id: "novel-1",
  chapters: [{ id: "chapter-1", batchId: "batch-1" }],
  pendingAiEdits: [],
  activeJob: null,
  limits: { chapterBodyMaxLength: 20000 },
} as unknown as NovelDetailResponse;

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
  isIllustrationsOn,
  isFixMode,
  target = chapter,
}: {
  isIllustrationsOn: boolean;
  isFixMode: boolean;
  target?: NovelChapterResponse;
}): string {
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: new QueryClient() },
      createElement(NovelChapterText, {
        novel,
        chapter: target,
        isFixMode,
        aiEdit,
        onFocusFallback: () => {},
        onDraftDirtyChange: () => {},
        isIllustrationsOn,
        onFixModeRequest: () => {},
        onPickImage: () => Promise.resolve(undefined),
      }),
    ),
  );
}

describe("NovelChapterText 삽화", () => {
  it.each([true, false])("스위치가 꺼졌으면 고치기 모드(%s)여도 삽화 조작과 위치 확인 필요 목록이 없다", (isFixMode) => {
    const markup = render({ isIllustrationsOn: false, isFixMode });
    expect(markup).not.toContain("옮기기");
    expect(markup).not.toContain("바꾸기");
    expect(markup).not.toContain("떼기");
    expect(markup).not.toContain("위치 확인 필요");
    expect(markup).not.toContain("놓기");
    // 그림은 응답이 정한다 — 서버가 꺼짐에서 목록을 비우므로 실제로는 그림도 없다.
    expect(markup).toContain("https://img.example/placed.webp");
  });

  it("켜짐 + 고치기 모드면 그림 아래 옮기기·바꾸기·떼기와 위치 확인 필요 목록이 있다", () => {
    const markup = render({ isIllustrationsOn: true, isFixMode: true });
    expect(markup).toContain("옮기기");
    expect(markup).toContain("바꾸기");
    expect(markup).toContain("떼기");
    expect(markup).toContain("위치 확인 필요 삽화 1장");
    expect(markup).toContain('aria-label="1번째 문단 뒤 삽화"');
  });

  // 위치 확인 필요는 독자에게 빠진 그림이 있다는 경고라 고치기 모드가 아니어도 선다. 문단 사이 그림의 조작은 고치기 모드에만.
  it("켜짐 + 고치기 모드가 아니면 그림 조작은 없고 위치 확인 필요 목록은 있다", () => {
    const markup = render({ isIllustrationsOn: true, isFixMode: false });
    expect(markup).not.toContain("옮기기");
    expect(markup).not.toContain("바꾸기");
    expect(markup).toContain("위치 확인 필요 삽화 1장");
    expect(markup).toContain("놓기");
  });

  // 위치 확인 필요라 공개 심사에서 빠져 있던 내린 그림을 다시 놓으면 다음 공개가 거부된다 — 목록에서도 떼기만 둔다.
  it("위치 확인 필요인 내린 그림에는 놓기가 없고 떼기만 있다", () => {
    const takenDown = {
      ...chapter,
      revision: {
        ...chapter.revision,
        unplacedIllustrations: [
          illustration("lost", { anchorBlockId: null, placement: null, url: null, withheld: "taken_down" }),
        ],
      },
    } satisfies NovelChapterResponse;
    const markup = render({ isIllustrationsOn: true, isFixMode: true, target: takenDown });
    const list = markup.slice(markup.indexOf("위치 확인 필요 삽화 1장"), markup.indexOf("첫 문단"));
    expect(list).not.toContain("놓기");
    expect(list).toContain("떼기");
  });

  // 내린 그림은 옮겨도 공개할 수 없는 것이 그대로라 옮기기는 없고, 다른 그림으로 바꾸거나 떼야 다시 공개할 수 있다.
  it("문단 사이의 내린 그림에는 바꾸기·떼기만 있다", () => {
    const takenDown = {
      ...chapter,
      revision: {
        ...chapter.revision,
        illustrations: [illustration("placed", { url: null, withheld: "taken_down" })],
        unplacedIllustrations: [],
      },
    } satisfies NovelChapterResponse;
    const markup = render({ isIllustrationsOn: true, isFixMode: true, target: takenDown });
    expect(markup).toContain("바꾸기");
    expect(markup).toContain("떼기");
    expect(markup).not.toContain("옮기기");
  });
});
