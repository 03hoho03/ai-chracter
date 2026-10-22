// 화 본문 블록(문단과 그 사이 삽화)의 마크업. 쪽 나누기·읽은 자리는 `[data-paragraph-index]` 만 세므로, 그림 블록에는
// 그 속성이 없어야 문단 순번 = 문단 번호가 유지된다.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { toPageTypography } from "../lib/pageFormat";
import { toReaderBlocks } from "../lib/readerBlocks";
import type { ViewerIllustration } from "../model/viewerSource";
import { PagedEpisodeBlocks, ScrollEpisodeBlocks } from "./EpisodeBlocks";

const PARAGRAPHS = ["첫 문단", "둘째 문단", "셋째 문단"];
const TYPOGRAPHY = toPageTypography({ fontSize: "small", lineHeight: "relaxed" });

function illustration(overrides: Partial<ViewerIllustration>): ViewerIllustration {
  return {
    paragraphIndex: 0,
    placement: "after",
    order: 0,
    source: "upload",
    url: "https://cdn.example/a.webp",
    width: 768,
    height: 1024,
    withheld: null,
    withheldReason: null,
    ...overrides,
  };
}

function renderPaged(illustrations: ViewerIllustration[], paragraphs = PARAGRAPHS): string {
  return renderToStaticMarkup(
    createElement(PagedEpisodeBlocks, {
      paragraphs,
      blocks: toReaderBlocks(paragraphs.length, illustrations),
      typography: TYPOGRAPHY,
    }),
  );
}

function renderScroll(illustrations: ViewerIllustration[], paragraphs = PARAGRAPHS): string {
  return renderToStaticMarkup(
    createElement(ScrollEpisodeBlocks, { paragraphs, blocks: toReaderBlocks(paragraphs.length, illustrations) }),
  );
}

/** 마크업에서 `data-paragraph-index` 를 단 요소의 (번호, 글) 순서. 문단이 아닌 요소가 그 속성을 달면 글 자리가 빈다. */
function paragraphsIn(html: string): [string, string][] {
  return Array.from(html.matchAll(/<(\w+) [^>]*?data-paragraph-index="(\d+)"[^>]*>([^<]*)</g), (match) => [
    match[2] ?? "",
    match[1] === "p" ? (match[3] ?? "") : `<${match[1] ?? ""}>`,
  ]);
}

const MIXED = [
  illustration({ paragraphIndex: 0, placement: "before" }),
  illustration({ paragraphIndex: 1, placement: "after", source: "original" }),
  illustration({ paragraphIndex: 2, placement: "after", url: null, withheld: "taken_down", withheldReason: "운영 사유" }),
];

describe("PagedEpisodeBlocks", () => {
  it("renders a chapter without illustrations exactly as before — last paragraph without a bottom gap", () => {
    expect(renderPaged([])).toBe(
      '<div class="text-foreground" style="font-size:16px;line-height:1.625">' +
        '<p data-paragraph-index="0" class="whitespace-pre-line text-pretty break-keep" style="margin-bottom:16px">첫 문단</p>' +
        '<p data-paragraph-index="1" class="whitespace-pre-line text-pretty break-keep" style="margin-bottom:16px">둘째 문단</p>' +
        '<p data-paragraph-index="2" class="whitespace-pre-line text-pretty break-keep" style="margin-bottom:0">셋째 문단</p>' +
        "</div>",
    );
  });

  it("keeps paragraph numbering untouched by illustration blocks", () => {
    expect(paragraphsIn(renderPaged(MIXED))).toEqual([
      ["0", "첫 문단"],
      ["1", "둘째 문단"],
      ["2", "셋째 문단"],
    ]);
  });

  it("sizes the image box in px from the response size, and the image cannot be dragged", () => {
    const html = renderPaged([illustration({ paragraphIndex: 1, width: 1280, height: 720 })]);
    expect(html).toContain('style="width:312px;height:176px"');
    expect(html).toMatch(/<img [^>]*draggable="false"/);
    expect(html).toMatch(/<figure [^>]*class="[^"]*break-inside-avoid/);
    expect(html).not.toMatch(/rem|%/);
  });

  it("gives the gap to the last paragraph when an illustration follows it, and none to the last block", () => {
    const html = renderPaged([illustration({ paragraphIndex: 2, placement: "after" })]);
    expect(html).toMatch(/<p data-paragraph-index="2"[^>]*style="margin-bottom:16px"/);
    expect(html).toMatch(/<figure [^>]*style="margin-bottom:0"/);
  });

  it("captions an original image, and only that", () => {
    expect(renderPaged([illustration({ source: "original" })])).toContain("원작 이미지");
    expect(renderPaged([illustration({ source: "generated" })])).not.toContain("원작 이미지");
  });

  it("marks where each illustration stands so the page split can find it", () => {
    const html = renderPaged([illustration({ paragraphIndex: 1, placement: "before" })]);
    expect(html).toMatch(/data-illustration-key="1-before-0"/);
    expect(html).toMatch(/data-illustration-paragraph="1"/);
    expect(html).toMatch(/data-illustration-placement="before"/);
  });

  it("shows a notice instead of the image for a taken-down illustration, its reason clamped to three lines", () => {
    const html = renderPaged([
      illustration({ url: null, withheld: "taken_down", withheldReason: "운영 사유", source: "original" }),
    ]);
    expect(html).not.toContain("<img");
    expect(html).toContain("운영 정책에 따라 내린 그림이에요");
    expect(html).toMatch(/line-clamp-3[^>]*>운영 사유</);
    expect(html).toContain('role="note"');
    expect(html).not.toContain("원작 이미지");
  });

  it("shows the restricted-original notice without a reason", () => {
    const html = renderPaged([illustration({ url: null, withheld: "original_restricted", source: "original" })]);
    expect(html).not.toContain("<img");
    expect(html).toContain("원작이 이용 제한 중이라 이 그림은 보여 드릴 수 없어요");
  });
});

describe("ScrollEpisodeBlocks", () => {
  it("renders a chapter without illustrations exactly as before", () => {
    expect(renderScroll([])).toBe(
      '<div class="flex flex-col gap-4 text-foreground">' +
        '<p data-paragraph-index="0" class="scroll-mt-4-safe whitespace-pre-line text-pretty break-keep">첫 문단</p>' +
        '<p data-paragraph-index="1" class="scroll-mt-4-safe whitespace-pre-line text-pretty break-keep">둘째 문단</p>' +
        '<p data-paragraph-index="2" class="scroll-mt-4-safe whitespace-pre-line text-pretty break-keep">셋째 문단</p>' +
        "</div>",
    );
  });

  it("keeps paragraph numbering untouched by illustration blocks", () => {
    expect(paragraphsIn(renderScroll(MIXED))).toEqual([
      ["0", "첫 문단"],
      ["1", "둘째 문단"],
      ["2", "셋째 문단"],
    ]);
  });

  it("holds the image's place before it arrives, cannot be dragged, and captions an original image", () => {
    const html = renderScroll([illustration({ source: "original" })]);
    expect(html).toContain("aspect-ratio:768 / 1024");
    expect(html).toMatch(/<img [^>]*draggable="false"/);
    expect(html).toContain("원작 이미지");
  });

  it("shows the whole reason of a taken-down illustration", () => {
    const html = renderScroll([illustration({ url: null, withheld: "taken_down", withheldReason: "운영 사유" })]);
    expect(html).not.toContain("<img");
    expect(html).toContain("운영 정책에 따라 내린 그림이에요");
    expect(html).toContain("운영 사유");
    expect(html).not.toContain("line-clamp");
  });
});
