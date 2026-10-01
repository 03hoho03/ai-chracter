import { describe, expect, it } from "vitest";

import type { CreationGuideTopicId } from "@/shared/config/creationGuide";

import { GUIDE_TOPICS } from "../config/topics";
import { findDisallowedTags } from "./findDisallowedTags";
import { parseManuscript, type ManuscriptSegment } from "./parseManuscript";

// 실원고 형식 검사. 원고는 사람이 쓰는 글이라 틀린 표기가 조용히 화면에 새지 않게 여기서 막는다.

/**
 * 튜토리얼 시드에 아직 데이터가 없어 시드를 인용할 수 없는 빌더 탭. 탭 id 와 그 탭의 시드 JSON 최상위 키를
 * 함께 적는다. 튜토리얼 예시 작품에는 미디어 북을 일부러 넣지 않았다.
 * 아래 "seed-less tab exceptions" 검사가 이 목록이 다른 탭을 가리지 못하게 잡는다.
 */
const TABS_WITHOUT_TUTORIAL_SEED: Partial<Record<CreationGuideTopicId, readonly { tabId: string; seedKey: string }[]>> = {
  story: [{ tabId: "mediaBook", seedKey: "mediaBook" }],
};

/** 시드 JSON 은 테스트 안에서만 읽는다(`seedQuotes.test.ts` 와 같은 이유 — 앱 모듈로 옮기면 운영 번들에 실린다). */
const TUTORIAL_STORY_SEEDS = import.meta.glob<string>(
  "../../../../../api/scripts/seed_content/data/tutorial/stories/*.json",
  { query: "?raw", import: "default", eager: true },
);

/** 탭 단계 절마다 시드 인용 블록 수를 센다(탭 단계 절이 아닌 절의 인용은 세지 않는다). */
function countSeedQuotesByStep(segments: readonly ManuscriptSegment[], stepIds: ReadonlySet<string>): Map<string, number> {
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
  return seedQuoteCount;
}

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

  // 단계마다 예시 작품의 실제 문안을 하나 이상 보여 준다(시드에 아직 데이터가 없는 탭만 빼고).
  it("quotes the seed at least once in every builder-tab section", () => {
    if (!topic.steps) return;
    const stepIds = new Set<string>(topic.steps.map((step) => step.id));
    const exemptTabIds = new Set((TABS_WITHOUT_TUTORIAL_SEED[topic.id] ?? []).map((exception) => exception.tabId));
    const emptySteps = [...countSeedQuotesByStep(segments, stepIds)]
      .filter(([id, count]) => count === 0 && !exemptTabIds.has(id))
      .map(([id]) => id);
    expect(emptySteps).toEqual([]);
  });
});

describe("seed-less tab exceptions", () => {
  const cases = GUIDE_TOPICS.flatMap((topic) =>
    (TABS_WITHOUT_TUTORIAL_SEED[topic.id] ?? []).map((exception) => [topic.id, exception.tabId, topic, exception] as const),
  );

  it("are listed only for the story guide (the only one with seed-less tabs today)", () => {
    expect(Object.keys(TABS_WITHOUT_TUTORIAL_SEED)).toEqual(["story"]);
  });

  // 지운 탭이나 오타가 남아 있으면 같은 이름의 새 탭이 검사 없이 지나간다.
  it.each(cases)("%s/%s names an existing builder tab", (_topicId, tabId, topic) => {
    expect((topic.steps ?? []).map((step) => step.id)).toContain(tabId);
  });

  // 시드에 데이터가 생기면 예외가 낡는다 — 그때는 원고가 시드를 인용하고 이 항목을 지운다.
  it.each(cases)("%s/%s still has no data in any tutorial story seed", (_topicId, _tabId, _topic, exception) => {
    const seedPaths = Object.keys(TUTORIAL_STORY_SEEDS);
    expect(seedPaths.length).toBeGreaterThan(0);
    for (const [path, raw] of Object.entries(TUTORIAL_STORY_SEEDS)) {
      const seed: unknown = JSON.parse(raw);
      const value = typeof seed === "object" && seed !== null ? Reflect.get(seed, exception.seedKey) : undefined;
      expect(value, `${path} 에 ${exception.seedKey} 가 생겼다`).toBeUndefined();
    }
  });

  // 원고가 이미 시드를 인용한다면 예외가 필요 없다 — 남겨 두면 나중에 인용을 지워도 안 잡힌다.
  it.each(cases)("%s/%s section quotes no seed yet", (_topicId, tabId, topic) => {
    const { segments } = parseManuscript(topic.manuscript);
    expect(countSeedQuotesByStep(segments, new Set([tabId])).get(tabId)).toBe(0);
  });
});
