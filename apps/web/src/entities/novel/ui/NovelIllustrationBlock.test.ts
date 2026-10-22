// 글 흐름 속 그림 블록의 면. 판 이력 모달은 `popover` 표면이라 `bg-muted` 웰·안내 상자가 그 위에서 사라진다 — 놓인 면을
// 받아 모달에서는 `secondary` 로 칠하는지 본다.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ViewerIllustration } from "../model/readerBlocks";
import { NovelIllustrationFigure } from "./NovelIllustrationBlock";

function illustration(overrides: Partial<ViewerIllustration>): ViewerIllustration {
  return {
    paragraphIndex: 0,
    placement: "after",
    order: 0,
    source: "upload",
    url: null,
    width: null,
    height: null,
    withheld: null,
    withheldReason: null,
    ...overrides,
  };
}

function render(target: ViewerIllustration, surface: "muted" | "secondary"): string {
  return renderToStaticMarkup(createElement(NovelIllustrationFigure, { illustration: target, surface }));
}

describe("NovelIllustrationFigure", () => {
  const cases: [string, ViewerIllustration][] = [
    ["주소 없는 그림 자리", illustration({})],
    ["그림 웰", illustration({ url: "https://cdn.example/a.webp", width: 768, height: 1024 })],
    ["내린 그림 안내", illustration({ withheld: "taken_down", withheldReason: "사유" })],
    ["원작 제한 안내", illustration({ withheld: "original_restricted" })],
  ];

  it.each(cases)("모달 면이면 %s 이 secondary 로 칠해지고 muted 가 없다", (_, target) => {
    const markup = render(target, "secondary");
    expect(markup).toContain("bg-secondary");
    expect(markup).not.toContain("bg-muted");
  });

  it.each(cases)("페이지 면이면 %s 이 지금처럼 muted 다", (_, target) => {
    const markup = render(target, "muted");
    expect(markup).toContain("bg-muted");
    expect(markup).not.toContain("bg-secondary");
  });
});
