import { describe, expect, it } from "vitest";

import { matchTabForPath } from "@/features/build-common";
import {
  type FieldLabel,
  MAX_STAT_RULES,
  PROMPT_TEMPLATE_LABELS,
  STICKY_TURN_OPTIONS,
  STORY_FIELD_LABELS,
  STORY_TABS,
  TARGET_LABELS,
  VISIBILITY_LABELS,
} from "@/features/build-story";
import type { CreationGuideTopicId } from "@/shared/config/creationGuide";

import { GUIDE_IMAGE_PLACEHOLDER, GUIDE_IMAGES } from "../config/guideImages";
import { READ_TIMING_GROUPS, STORY_FIELD_MOCKUPS, type StoryFieldMockups } from "../config/storyFieldMockups";
import mockupTableSource from "../config/storyFieldMockups.ts?raw";
import { GUIDE_TOPICS, type GuideTopic } from "../config/topics";
import { findDisallowedTags } from "./findDisallowedTags";
import { blockReadTiming, isStoryFieldKey, mockupCaption, selectedMediaCellName } from "./mockupCaption";
import { parseMockupValue } from "./mockupValue";
import {
  type GuideFieldBlock,
  type GuideItem,
  type GuideNoteBlock,
  type Manuscript,
  parseManuscript,
} from "./parseManuscript";
import { toGuidePages } from "./toGuidePages";

// 실원고 형식 검사. 원고는 사람이 쓰는 글이라 틀린 표기가 조용히 화면에 새지 않게 여기서 막는다. 표기 자체의 엄격함은
// 파서가 던지는 오류가 맡고, 여기서는 원고 내용이 빌더·목업 표와 맞는지를 본다. 시드 대조는 `seedQuotes.test.ts`.

/**
 * 튜토리얼 시드에 데이터가 없어 시드를 인용할 수 없는 빌더 탭. 탭 id 와 그 탭의 데이터가 시드 JSON 에 놓일 경로를 함께
 * 적는다(점으로 잇고, `*` 는 배열의 모든 항목).
 * 튜토리얼 시드에는 미디어 북이 없다. 서비스에 올린 예시 작품에는 미디어 북이 있지만, 시드 적재가 미디어 북을 싣지 않고
 * 칸마다 이미지가 필요해 시드에 글만 넣을 수도 없다. 그래서 이 탭의 예시는 원고의 free 값이다.
 * 아래 "seed-less tab exceptions" 검사가 이 목록이 다른 탭을 가리지 못하게 잡는다.
 */
const TABS_WITHOUT_TUTORIAL_SEED: Partial<Record<CreationGuideTopicId, readonly { tabId: string; seedPath: string }[]>> = {
  story: [
    { tabId: "mediaBook", seedPath: "mediaBook" },
  ],
};

/** 시드 JSON 은 테스트 안에서만 읽는다(`seedQuotes.test.ts` 와 같은 이유 — 앱 모듈로 옮기면 운영 번들에 실린다). */
const TUTORIAL_STORY_SEEDS = import.meta.glob<string>(
  "../../../../../api/scripts/seed_content/data/tutorial/stories/*.json",
  { query: "?raw", import: "default", eager: true },
);

/**
 * 시드 JSON 에서 점 경로가 가리키는 값을 모두 모은다(`*` 는 배열의 모든 항목). 경로 중간이 없으면 그 갈래는 값이 없다.
 * 최상위 키만 보면 시작설정 아래에 놓이는 목록은 늘 비어 보여, 시드에 데이터가 생겨도 예외가 낡은 줄 모른다.
 */
function valuesAtSeedPath(node: unknown, segments: readonly string[]): unknown[] {
  const [head, ...rest] = segments;
  if (head === undefined) return [node];
  if (head === "*") return Array.isArray(node) ? node.flatMap((item: unknown) => valuesAtSeedPath(item, rest)) : [];
  if (typeof node !== "object" || node === null) return [];
  return valuesAtSeedPath(Reflect.get(node, head), rest);
}

/** 화면에 보이는 글자 수 — 굵게·인라인 코드 표기와 링크 주소를 뺀 코드 포인트 수(공백 포함). */
function visibleLength(markdown: string): number {
  const visible = markdown
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\*\*/g, "")
    .replace(/`/g, "")
    .trim();
  return [...visible].length;
}

function isOneParagraph(markdown: string): boolean {
  return !/\n\s*\n/.test(markdown.trim());
}

type Block = GuideFieldBlock | GuideNoteBlock;

function blocksOf(manuscript: Manuscript): (Block & { sectionId: string })[] {
  return manuscript.sections.flatMap((section) =>
    section.content.flatMap((item) => (item.kind === "field" || item.kind === "note" ? [{ ...item, sectionId: section.id }] : [])),
  );
}

function fieldBlocksOf(manuscript: Manuscript): (GuideFieldBlock & { sectionId: string })[] {
  return blocksOf(manuscript).flatMap((block) => (block.kind === "field" ? [block] : []));
}

/** 블록 안의 산문·예시 조각 전부(본문·자세히·나쁜 예). */
function itemsInBlock(block: Block): GuideItem[] {
  if (block.kind === "note") return [...block.intro, ...(block.details ?? [])];
  return [...block.intro, ...(block.details ?? []), ...block.bad.flatMap((part) => part.prose)];
}

/** 블록 밖 절 본문의 산문 조각. */
function itemsOutsideBlocks(manuscript: Manuscript): GuideItem[] {
  return manuscript.sections.flatMap((section) =>
    section.content.flatMap((item) => (item.kind === "markdown" || item.kind === "example" ? [item] : [])),
  );
}

function allItems(manuscript: Manuscript): GuideItem[] {
  return [...itemsOutsideBlocks(manuscript), ...blocksOf(manuscript).flatMap(itemsInBlock)];
}

function markdownSources(items: readonly GuideItem[]): string[] {
  return items.flatMap((item) => (item.kind === "markdown" ? [item.source] : []));
}

/** 단계 절마다 시드 인용 수 — 산문 예시·목업 값·좋은 쪽 발췌를 블록 안팎 모두 센다. */
function countSeedQuotesByStep(manuscript: Manuscript, stepIds: ReadonlySet<string>): Map<string, number> {
  const counts = new Map<string, number>();
  for (const section of manuscript.sections) {
    if (!stepIds.has(section.id)) continue;
    const examples = [
      ...section.content.flatMap((item) => (item.kind === "example" ? [item] : [])),
      ...section.content.flatMap((item) => (item.kind === "field" || item.kind === "note" ? itemsInBlock(item) : [])),
    ].flatMap((item) => (item.kind === "example" ? [item.example.source] : []));
    const values = section.content.flatMap((item) =>
      item.kind === "field"
        ? [...item.values, ...item.bad.flatMap((part) => (part.good ? [part.good] : []))].map((value) => value.source)
        : [],
    );
    counts.set(section.id, [...examples, ...values].filter((source) => source.kind === "seed").length);
  }
  return counts;
}

const PARSED = GUIDE_TOPICS.map((topic) => [topic.id, topic, parseManuscript(topic.manuscript)] as const);

describe.each(PARSED)("%s manuscript", (_id, topic, manuscript) => {
  const pages = toGuidePages(manuscript, topic);

  it("renders only allowed tags in prose", () => {
    const offenders = markdownSources(allItems(manuscript)).flatMap((source) => {
      const tags = findDisallowedTags(source);
      return tags.length > 0 ? [{ tags, excerpt: source.slice(0, 80) }] : [];
    });
    expect(offenders).toEqual([]);
  });

  // 가이드 렌더러는 HTML 을 버리므로 주석으로 남긴 표식은 조용히 사라진다.
  it("contains no HTML comments", () => {
    expect(topic.manuscript).not.toContain("<!--");
  });

  // 표는 쓰지 않는다(GFM 없음). 줄 머리 `|` 는 요소를 만들지 않고 글자로 찍혀 태그 검사로는 안 잡힌다.
  it("has no table rows in prose", () => {
    const tableLines = markdownSources(allItems(manuscript)).flatMap((source) =>
      source.split("\n").filter((line) => line.startsWith("|")),
    );
    expect(tableLines).toEqual([]);
  });

  it("uses each section id once", () => {
    const ids = manuscript.sections.map((section) => section.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  // 단계 페이지 안 앵커(블록 id)가 겹치면 링크가 엉뚱한 블록으로 간다.
  it("uses each anchor once within a page", () => {
    for (const step of pages.steps) {
      const ids = step.content.flatMap((item) => (item.kind === "field" || item.kind === "note" ? [item.id] : []));
      expect(new Set(ids).size, step.id).toBe(ids.length);
    }
  });

  // 단계 절 id 가 빌더 탭 id 와 같아야 단계 페이지 경로와 빌더의 "작성 가이드" 링크가 성립한다.
  it("has one step per builder tab, in tab order", () => {
    expect(pages.steps.map((step) => step.id)).toEqual(topic.steps.map((step) => step.id));
  });

  // 단계마다 예시 작품의 실제 문안을 하나 이상 보여 준다(시드에 데이터가 없는 탭만 빼고).
  it("quotes the seed at least once in every step", () => {
    const stepIds = new Set(topic.steps.map((step) => step.id));
    const exemptTabIds = new Set((TABS_WITHOUT_TUTORIAL_SEED[topic.id] ?? []).map((exception) => exception.tabId));
    const emptySteps = [...countSeedQuotesByStep(manuscript, stepIds)]
      .filter(([id, count]) => count === 0 && !exemptTabIds.has(id))
      .map(([id]) => id);
    expect(emptySteps).toEqual([]);
  });

  // 원고 속 가이드 링크(`/guide/<토픽>/<단계>#<앵커>`)가 실제 단계와 블록을 가리켜야 한다.
  it("links only to existing guide pages and anchors", () => {
    const links = markdownSources(allItems(manuscript)).flatMap((source) =>
      [...source.matchAll(/\]\((\/guide\/[^)\s]*)\)/g)].map((match) => match[1] ?? ""),
    );
    const broken = links.filter((link) => {
      const [path = "", anchor] = link.split("#");
      const [, , topicId, stepId, ...rest] = path.split("/");
      if (topicId !== topic.id || rest.length > 0) return true;
      if (stepId === undefined) return anchor !== undefined && !pages.overview.before.concat(pages.overview.after).some((s) => s.id === anchor);
      const step = pages.steps.find((candidate) => candidate.id === stepId);
      if (!step) return true;
      if (anchor === undefined) return false;
      return !step.content.some((item) => (item.kind === "field" || item.kind === "note") && item.id === anchor);
    });
    expect(broken).toEqual([]);
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
    expect(topic.steps.map((step) => step.id)).toContain(tabId);
  });

  // 시드에 데이터가 생기면 예외가 낡는다 — 그때는 원고가 시드를 인용하고 이 항목을 지운다.
  it.each(cases)("%s/%s still has no data in any tutorial story seed", (_topicId, _tabId, _topic, exception) => {
    const seedPaths = Object.keys(TUTORIAL_STORY_SEEDS);
    expect(seedPaths.length).toBeGreaterThan(0);
    for (const [path, raw] of Object.entries(TUTORIAL_STORY_SEEDS)) {
      const seed: unknown = JSON.parse(raw);
      // 빈 목록(`[]`)은 인용할 데이터가 아니다 — 시드는 목록을 지울 때 빈 목록으로 적는다.
      const values = valuesAtSeedPath(seed, exception.seedPath.split(".")).filter(
        (value) => value !== undefined && !(Array.isArray(value) && value.length === 0),
      );
      expect(values, `${path} 에 ${exception.seedPath} 가 생겼다`).toEqual([]);
    }
  });

  // 원고가 이미 시드를 인용한다면 예외가 필요 없다 — 남겨 두면 나중에 인용을 지워도 안 잡힌다.
  it.each(cases)("%s/%s step quotes no seed yet", (_topicId, tabId, topic) => {
    expect(countSeedQuotesByStep(parseManuscript(topic.manuscript), new Set([tabId])).get(tabId)).toBe(0);
  });
});

// ── 칸 블록을 쓰는 토픽(스토리) ──────────────────────────────────────────────

const BLOCK_TOPICS = PARSED.flatMap(([id, topic, manuscript]) =>
  topic.fieldMockups ? [[id, topic, manuscript, topic.fieldMockups] as const] : [],
);

/** 선택지가 코드 상수에 있는 칸 → 고를 수 있는 값. 원고의 선택값이 이 밖이면 목업이 빌더에 없는 선택지를 그린다. */
const OPTION_VALUES: Partial<Record<string, readonly unknown[]>> = {
  "storySetting.promptTemplate": Object.keys(PROMPT_TEMPLATE_LABELS),
  "registration.target": Object.keys(TARGET_LABELS),
  "registration.visibility": Object.keys(VISIBILITY_LABELS),
  "keywordNotes.*.stickyTurns": STICKY_TURN_OPTIONS.map((option) => Number(option.value)),
};

/**
 * 선택지가 코드 상수에 없는 선택 칸과 그 이유. 장르 목록은 서버에서 받아 오고, 적용 대상은 "스토리 전체"(null) 또는 특정
 * 시작설정 id 다. 엔딩의 우선순위 스탯은 그 시작설정에 작가가 만든 스탯 가운데 하나라, 원고는 스탯 이름으로 적는다.
 */
const OPTIONS_OUTSIDE_CODE: Record<string, (value: unknown) => boolean> = {
  "registration.genre": (value) => typeof value === "string" && value !== "",
  "keywordNotes.*.scope": (value) => value === null || typeof value === "string",
  "startingSetups.*.endings.*.priorityStatId": (value) => typeof value === "string" && value !== "",
};

describe.each(BLOCK_TOPICS)("%s field blocks", (_id, topic: GuideTopic, manuscript, mockups: StoryFieldMockups) => {
  const pages = toGuidePages(manuscript, topic);
  const fieldBlocks = fieldBlocksOf(manuscript);
  const blocks = blocksOf(manuscript);
  const mediaCellName = selectedMediaCellName(pages.steps);

  it("uses only keys from the builder label constants, on the tab that owns them", () => {
    const misplaced = fieldBlocks.flatMap((block) =>
      block.keys.flatMap((key) => {
        if (!isStoryFieldKey(key)) return [`${key}: 라벨 상수에 없다`];
        const tabId = matchTabForPath(key, STORY_TABS);
        if (tabId !== block.sectionId) return [`${key}: ${block.sectionId} 단계에 있지만 빌더 탭은 ${tabId}`];
        if (mockups[key].kind === "group") return [`${key}: 탭 전체를 가리키는 키라 목업으로 그릴 수 없다`];
        return [];
      }),
    );
    expect(misplaced).toEqual([]);
  });

  it("has at least one field block in every step", () => {
    const empty = pages.steps.filter((step) => !step.content.some((item) => item.kind === "field")).map((step) => step.id);
    expect(empty).toEqual([]);
  });

  // 길이 상한은 390px 폭 단계 페이지 높이 예산에서 나온 값이다 — 넘치면 줄 수가 늘어 예산이 깨진다.
  it("keeps step summaries within 16 characters and leads within one 40-character paragraph", () => {
    const offenders = pages.steps.flatMap((step) => {
      const problems: string[] = [];
      if (visibleLength(step.summary) > 16) problems.push(`${step.id} 요약 ${visibleLength(step.summary)}자`);
      const lead = step.lead ?? "";
      if (visibleLength(lead) > 40 || !isOneParagraph(lead)) problems.push(`${step.id} 리드 ${visibleLength(lead)}자`);
      return problems;
    });
    expect(offenders).toEqual([]);
  });

  it("keeps each block's visible description within one 60-character paragraph", () => {
    const offenders = blocks.flatMap((block) => {
      const intro = markdownSources(block.intro).join("\n\n");
      return visibleLength(intro) > 60 || !isOneParagraph(intro) ? [`${block.id}: ${visibleLength(intro)}자`] : [];
    });
    expect(offenders).toEqual([]);
  });

  // 제목은 평문으로 그린다. 묶음 제목이 라벨과 같으면 첫 키를 그 칸으로 두면 되므로 사본을 막는다.
  it("keeps block, note and bad-part titles short and plain", () => {
    const labels = new Set<string>(Object.values(STORY_FIELD_LABELS).map((label) => label.label));
    const offenders = blocks.flatMap((block) => {
      const titles =
        block.kind === "note"
          ? [{ title: block.title, max: 16 }]
          : [
              ...(block.title === null ? [] : [{ title: block.title, max: 16 }]),
              ...block.bad.map((part) => ({ title: part.title, max: 12 })),
            ];
      const problems = titles.flatMap(({ title, max }) =>
        [...title].length > max || /[*`]/.test(title) || labels.has(title) ? [`${block.id}: "${title}"`] : [],
      );
      // 제목 없는 여러 키 블록은 첫 키가 나머지 키의 목록이어야 h2(첫 키 라벨)가 블록 전체를 말한다.
      if (block.kind === "field" && block.title === null && block.keys.length > 1) {
        const [listKey, ...cardKeys] = block.keys;
        if (!cardKeys.every((key) => key.startsWith(`${listKey}.*.`))) problems.push(`${block.id}: 여러 키 블록에 제목이 없다`);
      }
      return problems;
    });
    expect(offenders).toEqual([]);
  });

  // 원고의 "N자" 는 빌더 스키마 상한의 사본이다 — 칸 블록 안에서만, 그 블록 칸의 상한과 같은 숫자로만 쓴다.
  it("states character limits only inside blocks and only as the block's own limit", () => {
    const numbersIn = (sources: readonly string[]) =>
      sources.flatMap((source) => [...source.matchAll(/(\d+)\s?자/g)].map((match) => Number(match[1])));
    const outside = numbersIn(markdownSources(itemsOutsideBlocks(manuscript)));
    const inside = blocks.flatMap((block) => {
      const limits = new Set(
        block.kind === "field" ? block.keys.flatMap((key) => (isStoryFieldKey(key) ? [mockups[key].limit ?? -1] : [])) : [],
      );
      return numbersIn(markdownSources(itemsInBlock(block)))
        .filter((count) => !limits.has(count))
        .map((count) => `${block.id}: ${count}자`);
    });
    expect({ outside, inside }).toEqual({ outside: [], inside: [] });
  });

  it("names at most one read timing per block and keeps every caption on one line", () => {
    const captions = fieldBlocks.map((block) => mockupCaption(block, mockups, mediaCellName));
    expect(captions.filter((caption) => [...caption].length > 24)).toEqual([]);
  });

  // 개요 "AI가 읽는 때" 목록의 칸 링크가 갈 블록이 있어야 한다.
  it("has a block for every key the read-timing table lists", () => {
    const listed = Object.entries(mockups).flatMap(([key, mockup]) => (mockup.readTiming ? [key] : []));
    expect(listed.filter((key) => !pages.anchorOfKey.has(key))).toEqual([]);
    for (const block of fieldBlocks) expect(() => blockReadTiming(block, mockups)).not.toThrow();
  });

  it("writes every mockup value in the shape of its field", () => {
    const problems = fieldBlocks.flatMap((block) =>
      [...block.values, ...block.bad.flatMap((part) => [...part.values, ...(part.good ? [part.good] : [])])].flatMap((value) => {
        if (!isStoryFieldKey(value.key)) return [];
        const mockup = mockups[value.key];
        try {
          const parsed = parseMockupValue(mockup.kind, value.body);
          return valueProblems(value.key, parsed, mockup.limit).map((problem) => `${value.line}번째 줄 ${value.key}: ${problem}`);
        } catch (error) {
          return [`${value.line}번째 줄 ${value.key}: ${error instanceof Error ? error.message : String(error)}`];
        }
      }),
    );
    expect(problems).toEqual([]);
  });

  // 빈 값으로 그리는 칸은 빌더의 자리표시를 보여 줘야 칸이 비어 있다는 것이 읽힌다(빌더도 같은 상수를 읽는다).
  it("gives every empty mockup value a builder placeholder", () => {
    const missing = fieldBlocks.flatMap((block) =>
      block.values.flatMap((value) => {
        if (!isStoryFieldKey(value.key)) return [];
        const parsed = parseMockupValue(mockups[value.key].kind, value.body);
        const isEmpty = (parsed.kind === "chips" && parsed.items.length === 0) || ("text" in parsed && parsed.text.trim() === "");
        const label: FieldLabel = STORY_FIELD_LABELS[value.key];
        return isEmpty && label.placeholder === undefined ? [value.key] : [];
      }),
    );
    expect(missing).toEqual([]);
  });

  it("draws the media book grid inside its people and scenes", () => {
    const values = new Map(fieldBlocks.flatMap((block) => block.values.map((value) => [value.key, value.body] as const)));
    const grid = parseMockupValue("mediaGrid", values.get("mediaBook.cells") ?? "");
    const people = parseMockupValue("chips", values.get("mediaBook.people") ?? "");
    const scenes = parseMockupValue("chips", values.get("mediaBook.scenes") ?? "");
    if (grid.kind !== "mediaGrid" || people.kind !== "chips" || scenes.kind !== "chips") throw new Error("배치표 값 모양");

    const inRange = (position: { person: number; scene: number }) =>
      position.person < people.items.length && position.scene < scenes.items.length;
    const cellIds = grid.cells.map((cell) => `${cell.person}/${cell.scene}`);
    expect(grid.cells.every(inRange)).toBe(true);
    expect(new Set(cellIds).size).toBe(cellIds.length);
    expect(cellIds).toContain(`${grid.selected.person}/${grid.selected.scene}`);
    expect(mediaCellName).not.toBeNull();
  });
});

function valueProblems(key: string, value: ReturnType<typeof parseMockupValue>, limit: number | undefined): string[] {
  const problems: string[] = [];
  const tooLong = (text: string) => limit !== undefined && [...text].length > limit;
  switch (value.kind) {
    case "text":
    case "textarea":
      if (tooLong(value.text)) problems.push(`${limit}자를 넘는다`);
      break;
    case "chips":
      if (value.items.some(tooLong)) problems.push(`${limit}자를 넘는 칩`);
      break;
    case "statChangeRules": {
      // 규칙 줄은 빌더 조건 칸의 상한을 지켜야 그림이 빌더에서 쓸 수 없는 글을 보이지 않는다.
      const conditionLimit = STORY_FIELD_MOCKUPS["startingSetups.*.stats.*.rules.*.condition"].limit;
      if (value.rules.some((rule) => [...rule.condition.trim()].length > conditionLimit)) {
        problems.push(`${conditionLimit}자를 넘는 조건`);
      }
      if (value.rules.length > MAX_STAT_RULES) problems.push(`규칙이 ${MAX_STAT_RULES}개를 넘는다`);
      break;
    }
    case "toggle":
    case "select": {
      const options = OPTION_VALUES[key];
      const isAllowed = options ? options.includes(value.value) : OPTIONS_OUTSIDE_CODE[key]?.(value.value);
      if (!isAllowed) problems.push(`선택지 밖의 값 ${JSON.stringify(value.value)}`);
      break;
    }
    case "image":
      if (value.token !== GUIDE_IMAGE_PLACEHOLDER && !Object.hasOwn(GUIDE_IMAGES, value.token)) {
        problems.push(`모르는 그림 ${value.token}`);
      }
      break;
    default:
      break;
  }
  return problems;
}

describe("story field mockup table", () => {
  // 목업 표가 라벨 상수와 같은 키 집합이어야 원고 칸 키 검사(라벨 상수에 있음)가 목업 표에도 그대로 선다.
  it("covers exactly the builder label keys", () => {
    expect(Object.keys(STORY_FIELD_MOCKUPS).sort()).toEqual(Object.keys(STORY_FIELD_LABELS).sort());
  });

  // 카드 안 칸 키의 목록 키(`startingSetups.*.stats.*.name` → `startingSetups.*.stats`)가 상수에 있어야 캡션의
  // "<목록 라벨> 카드 안" 과 카드 목록 블록이 성립한다.
  it("has a list key for every key inside a card", () => {
    const missing = Object.keys(STORY_FIELD_LABELS).flatMap((key) => {
      const lastStar = key.lastIndexOf(".*");
      return lastStar !== -1 && !isStoryFieldKey(key.slice(0, lastStar)) ? [key] : [];
    });
    expect(missing).toEqual([]);
  });

  // 상한 숫자를 표에 직접 적으면 빌더 스키마가 바뀔 때 목업과 원고 검사만 옛 숫자에 남는다.
  it("takes every limit from a schema constant, not a number literal", () => {
    expect(mockupTableSource).not.toMatch(/limit:\s*\d/);
  });

  // 읽는 때 글자는 원고 검사(허용 태그·인용 금지 표기) 밖의 코드 문자열이라 평문만 쓴다.
  it("keeps read-timing group texts plain", () => {
    const texts = READ_TIMING_GROUPS.flatMap((group) => [group.title, group.caption]);
    expect(texts.filter((text) => /[*`#]|[A-Z]{1,3}-\d/.test(text))).toEqual([]);
  });
});
