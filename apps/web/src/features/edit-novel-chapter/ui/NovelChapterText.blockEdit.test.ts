// 보드 화 본문이 여러 문단 수정 스위치와 남은 수정안에 따라 무엇을 그리는가. 스위치가 꺼져 있으면 고르기 안내와 버튼이 옛 연속
// 범위 그대로이고, 스위치와 상관없이 받은 수정안은 그 블록 자리에 보인다(스위치를 끈 뒤에도 적용·버리기는 된다).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { NovelChapterResponse, NovelDetailResponse, NovelPendingBlockEdit } from "@/entities/novel";

import { NovelChapterText } from "./NovelChapterText";

const PARAGRAPHS = ["창가에 기대 섰다.", "정말로 받아들이겠다는 거야?", "고개를 끄덕였다.", "그래, 받아들일게.", "목소리는 떨리지 않았다."];

const chapter = {
  id: "chapter-1",
  novelId: "novel-1",
  ordinal: 3,
  assistantMessageCount: 4,
  revision: {
    id: "r1",
    revisionNo: 2,
    source: "generate",
    revertedFromRevisionId: null,
    createdAt: "2026-10-24T00:00:00Z",
    body: PARAGRAPHS.join("\n\n"),
    paragraphs: PARAGRAPHS,
    blocks: PARAGRAPHS.map((text, index) => ({ id: `b${index}`, text })),
    illustrations: [],
    unplacedIllustrations: [],
    scenes: [],
  },
} satisfies NovelChapterResponse;

/** 시안의 예: 2(b1)는 독립 수정안, 4+5(b3·b4)는 묶음이고 5는 사용자가 고쳐 지금 쓸 수 없다. */
const pendingBlockEdit: NovelPendingBlockEdit = {
  id: "job-1",
  chapterId: "chapter-1",
  instruction: "대사를 줄이고 차분하게",
  patches: [
    { id: "p1", blockId: "b1", state: "pending", paragraphs: ["정말 받아들일 거야?"], fresh: true },
    { id: "p3", blockId: "b3", state: "pending", paragraphs: ["받아들일게."], fresh: true },
    { id: "p4", blockId: "b4", state: "pending", paragraphs: ["목소리는 고요했다."], fresh: false },
  ],
  bundles: [{ id: "u1", patchIds: ["p3", "p4"], reason: "5가 4의 대사를 받아요" }],
  createdAt: "2026-10-24T00:00:00Z",
};

function novelWith(pendingBlockEdits: NovelPendingBlockEdit[] | undefined): NovelDetailResponse {
  return {
    id: "novel-1",
    chapters: [{ id: "chapter-1", batchId: "batch-1", ordinal: 3 }],
    pendingAiEdits: [],
    ...(pendingBlockEdits === undefined ? {} : { pendingBlockEdits }),
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
  isFixMode,
  isMultiBlockEditOn,
}: {
  novel: NovelDetailResponse;
  isFixMode: boolean;
  isMultiBlockEditOn: boolean | undefined;
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
        ...(isMultiBlockEditOn === undefined ? {} : { isMultiBlockEditOn }),
      }),
    ),
  );
}

describe("NovelChapterText 여러 문단 고르기", () => {
  // 스냅숏은 여러 문단 수정을 더하기 전 코드로 찍었다 — 스위치가 꺼진 화면은 그때와 글자 하나까지 같다.
  it.each([true, false])("스위치가 꺼졌으면 고치기 모드(%s) 화면이 여러 문단 수정 전과 같다", (isFixMode) => {
    expect(render({ novel: novelWith(undefined), isFixMode, isMultiBlockEditOn: false })).toMatchSnapshot();
  });

  it("스위치가 꺼졌으면 옛 연속 범위 안내다", () => {
    const markup = render({ novel: novelWith(undefined), isFixMode: true, isMultiBlockEditOn: false });
    expect(markup).toContain("이어진 문단을 함께 고를 수 있어요.");
    expect(markup).not.toContain("떨어진 문단도");
  });

  it("스위치가 켜졌으면 떨어진 문단도 같은 장면 안에서 고를 수 있다고 안내한다", () => {
    const markup = render({ novel: novelWith(undefined), isFixMode: true, isMultiBlockEditOn: true });
    expect(markup).toContain("같은 장면 안이면 떨어진 문단도 함께 고를 수 있어요");
    expect(markup).toContain("20개");
    expect(markup).not.toContain("이어진 문단을 함께 고를 수 있어요.");
  });
});

describe("NovelChapterText 여러 문단 수정안", () => {
  it.each([true, false])("스위치(%s)와 상관없이 수정안은 그 블록 자리에서 수정안 쪽으로 보인다", (isMultiBlockEditOn) => {
    const markup = render({ novel: novelWith([pendingBlockEdit]), isFixMode: false, isMultiBlockEditOn });
    expect(markup).toContain("정말 받아들일 거야?");
    expect(markup).not.toContain("정말로 받아들이겠다는 거야?");
    expect(markup).toContain("받아들일게.");
    // 손대지 않은 문단은 그대로다.
    expect(markup).toContain("고개를 끄덕였다.");
    expect(markup).toContain("수정안");
    expect(markup).toContain("지금 글");
  });

  it("독립 수정안에는 적용·버리기가, 묶음에는 함께 적용·함께 버리기가, 작업에는 모두 버리기가 있다", () => {
    const markup = render({ novel: novelWith([pendingBlockEdit]), isFixMode: false, isMultiBlockEditOn: true });
    expect(markup).toContain(">적용<");
    expect(markup).toContain(">버리기<");
    expect(markup).toContain("함께 적용");
    expect(markup).toContain("함께 버리기");
    expect(markup).toContain("5가 4의 대사를 받아요");
    expect(markup).toContain("남은 수정안 모두 버리기");
    expect(markup).toContain("대사를 줄이고 차분하게");
  });

  it("글이 바뀐 수정안은 지금 글을 보이고 적용할 수 없다고 말하며, 그 묶음의 함께 적용을 막는다", () => {
    const markup = render({ novel: novelWith([pendingBlockEdit]), isFixMode: false, isMultiBlockEditOn: true });
    expect(markup).toContain("글이 바뀌어 적용할 수 없어요");
    expect(markup).toContain("목소리는 떨리지 않았다.");
    expect(markup).not.toContain("목소리는 고요했다.");
    expect(markup).toMatch(/aria-disabled="true"[^>]*>함께 적용</);
  });

  it("고치기 모드에서 수정안이 놓인 문단은 고르는 버튼이 아니다", () => {
    const markup = render({ novel: novelWith([pendingBlockEdit]), isFixMode: true, isMultiBlockEditOn: true });
    expect(markup).toContain('aria-pressed="false"');
    expect(markup).not.toMatch(/<button[^>]*aria-pressed="false"[^>]*>정말로 받아들이겠다는 거야\?/);
    expect(markup).toMatch(/<button[^>]*aria-pressed="false"[^>]*>고개를 끄덕였다\./);
  });
});
