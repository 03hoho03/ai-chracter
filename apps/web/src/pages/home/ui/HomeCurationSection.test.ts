// 홈 큐레이션 카드는 비로그인 홈에도 나오고, 카드의 접근 이름이 한줄소개 문단을 가리킨다 — 작가 글의 `{{user}}` 가
// 보이는 글과 읽히는 글 양쪽에서 이름이 돼야 한다.
// 그리고 블록이 아래 그리드와 같은 열 사다리(컨테이너 쿼리)를 쓰므로 섹션 자신이 크기 컨테이너여야 한다.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { HomeCurationItem } from "@/entities/content";

import { HomeCurationSection } from "./HomeCurationSection";

function render(item: Partial<HomeCurationItem>, viewerPersonaName: string | null): string {
  return renderToStaticMarkup(
    createElement(HomeCurationSection, {
      item: {
        id: "content-1",
        type: "story",
        name: "상영회까지",
        oneLiner: "{{user}}는 영화 동아리의 조감독이다.",
        thumbnailUrl: null,
        ...item,
      },
      viewerPersonaName,
      onOpen: () => {},
    }),
  );
}

/** 카드(`role="button"`)가 이름으로 가리키는 노드들의 글. */
function accessibleNameText(html: string): string {
  const labelledBy = /role="button"[^>]*aria-labelledby="([^"]*)"/.exec(html)?.[1] ?? "";
  return labelledBy
    .split(" ")
    .map((id) => new RegExp(`id="${id}"[^>]*>([^<]*)<`).exec(html)?.[1] ?? "")
    .join(" ");
}

describe("HomeCurationSection", () => {
  it("puts the viewer's profile name into the one-liner and the card's accessible name", () => {
    const html = render({}, "지훈");
    expect(html).toContain("지훈은 영화 동아리의 조감독이다.");
    expect(accessibleNameText(html)).toBe("상영회까지 지훈은 영화 동아리의 조감독이다.");
  });

  it("falls back to the fallback name for a signed-out viewer", () => {
    expect(render({}, null)).toContain("당신은 영화 동아리의 조감독이다.");
  });

  it("is its own size container, since the column ladder it shares with the grid below is a container query", () => {
    expect(render({}, null)).toMatch(/^<section [^>]*class="(?:[^"]* )?@container[ "]/);
  });
});
