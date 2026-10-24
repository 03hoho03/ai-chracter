import { createMemoryHistory, createRootRoute, createRouter, RouterContextProvider } from "@tanstack/react-router";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { NovelDetailResponse } from "@/entities/novel";

import { BoardOverviewPanel } from "./BoardOverviewPanel";

const router = createRouter({
  routeTree: createRootRoute(),
  history: createMemoryHistory({ initialEntries: ["/"] }),
});

function render(novel: NovelDetailResponse): string {
  return renderToStaticMarkup(
    createElement(RouterContextProvider, {
      router,
      children: createElement(BoardOverviewPanel, { novel, characterCount: 2, headingRef: { current: null } }),
    }),
  );
}

describe("개요의 묶음 수", () => {
  it("구성안으로 쓴 화의 묶음은 묶음으로 세지 않는다", () => {
    const novel = {
      id: "n1",
      chapters: [
        { id: "c1", batchId: "b1", ordinal: 1, episodeOutlineId: null },
        { id: "c2", batchId: "b2", ordinal: 2, episodeOutlineId: "eo-2" },
        { id: "c3", batchId: "b3", ordinal: 3, episodeOutlineId: "eo-3" },
      ],
      batches: [{ id: "b1" }, { id: "b2" }, { id: "b3" }],
    } as unknown as NovelDetailResponse;
    expect(render(novel)).toContain("3화 · 묶음 1개 · 인물 2명");
  });

  it("옛 묶음이 없으면 묶음 칸을 뺀다", () => {
    const novel = {
      id: "n1",
      chapters: [{ id: "c1", batchId: "b1", ordinal: 1, episodeOutlineId: "eo-1" }],
      batches: [{ id: "b1" }],
    } as unknown as NovelDetailResponse;
    expect(render(novel)).toContain("1화 · 인물 2명");
  });
});
