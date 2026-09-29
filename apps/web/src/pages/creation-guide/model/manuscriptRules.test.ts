import { describe, expect, it } from "vitest";

import { GUIDE_TOPICS } from "../config/topics";
import { findDisallowedTags } from "./findDisallowedTags";
import { parseManuscript } from "./parseManuscript";

// 실원고 형식 검사. 원고는 사람이 쓰는 글이라 틀린 표기가 조용히 화면에 새지 않게 여기서 막는다.

describe.each(GUIDE_TOPICS.map((topic) => [topic.id, topic] as const))("%s manuscript", (_id, topic) => {
  const { segments, toc } = parseManuscript(topic.manuscript);

  it("renders only allowed tags outside example blocks", () => {
    const offenders = segments.flatMap((segment) => {
      if (segment.kind !== "markdown") return [];
      const tags = findDisallowedTags(segment.source);
      return tags.length > 0 ? [{ tags, excerpt: segment.source.slice(0, 80) }] : [];
    });
    expect(offenders).toEqual([]);
  });

  // 가이드 렌더러는 HTML 을 버리므로 주석으로 남긴 표식은 조용히 사라진다. 인용 표식은 예시 블록 여는 줄에 둔다.
  it("contains no HTML comments", () => {
    expect(topic.manuscript).not.toContain("<!--");
  });

  // 표는 쓰지 않는다(GFM 없음). 줄 머리 `|` 는 요소를 만들지 않고 글자로 찍혀 태그 검사로는 안 잡힌다.
  it("has no table rows outside example blocks", () => {
    const tableLines = segments.flatMap((segment) =>
      segment.kind === "markdown" ? segment.source.split("\n").filter((line) => line.startsWith("|")) : [],
    );
    expect(tableLines).toEqual([]);
  });

  it("uses each section id once", () => {
    const ids = toc.map((entry) => entry.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  // 절 id 가 빌더 탭 id 와 같아야 빌더에서 해당 절로 바로 거는 링크가 성립한다. 탭이 늘면 여기가 빨개진다.
  it("has one section per builder tab, in tab order", () => {
    // 빌더 탭과 짝이 없는 토픽은 `steps` 가 없다.
    if (!topic.steps) return;
    const stepIds: string[] = topic.steps.map((step) => step.id);
    const stepSectionIds = toc.map((entry) => entry.id).filter((id) => stepIds.includes(id));
    expect(stepSectionIds).toEqual(stepIds);
  });

  // 단계마다 예시 작품의 실제 문안을 하나 이상 보여 준다.
  it("quotes the seed at least once in every builder-tab section", () => {
    if (!topic.steps) return;
    const stepIds = new Set<string>(topic.steps.map((step) => step.id));
    const seedQuoteCount = new Map<string, number>();
    let currentId: string | undefined;
    for (const segment of segments) {
      if (segment.kind === "heading") {
        currentId = segment.id;
        if (stepIds.has(segment.id)) seedQuoteCount.set(segment.id, 0);
      } else if (segment.kind === "example" && segment.source.kind === "seed" && currentId !== undefined) {
        const count = seedQuoteCount.get(currentId);
        if (count !== undefined) seedQuoteCount.set(currentId, count + 1);
      }
    }
    const emptySteps = [...seedQuoteCount].filter(([, count]) => count === 0).map(([id]) => id);
    expect(emptySteps).toEqual([]);
  });
});
