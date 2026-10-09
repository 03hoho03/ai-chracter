import { describe, expect, it } from "vitest";

import { GUIDE_TOPICS, type GuideTopic } from "../config/topics";
import { isStoryFieldKey } from "./mockupCaption";
import { isRecord, parseMockupValue } from "./mockupValue";
import {
  type ExampleSource,
  type FieldValue,
  type GuideItem,
  type Manuscript,
  parseManuscript,
  type ProseExampleKind,
} from "./parseManuscript";

/**
 * 원고의 시드 인용이 튜토리얼 시드 JSON 과 같은지 대조한다. 같은 글이 시드와 원고 두 곳에 있어 한쪽만 고쳐지면 가이드가
 * 실제 예시 작품과 다른 글을 보여 주게 된다.
 *
 * - 글은 시드 값 전문이거나 시드 값의 **연속된 온전한 줄**이어야 한다(줄 중간을 자른 발췌는 안 된다). 좋은 쪽 발췌는
 *   두 줄까지, 반복 카드 목록의 글 조각은 전문이나 첫 줄(빌더 카드 머리 줄 요약이 첫 줄을 쓴다)이다. 줄바꿈 `\r\n` 만
 *   `\n` 으로 맞추고 다른 정규화는 하지 않는다.
 * - 글이 아닌 값(칩·선택값·숫자·규칙)은 JSON 으로 읽어 시드 값과 깊은 같음으로 본다.
 * - 목업 값은 칸 키와 시드 경로가 짝이어야 하고(시작상황 칸에 프롤로그를 인용하지 못하게), 한 블록의 값들은 같은 카드에서
 *   와야 한다(0번 질문과 1번 응답을 한 쌍으로 보이지 못하게).
 *
 * 시드 JSON 은 이 테스트 파일 안에서만 읽는다. 앱 코드 모듈로 옮기면 시드 본문이 운영 번들에 실린다. 파일이 앱
 * 밖(`apps/api`)에 있어 `web` CI 의 경로 필터에 그 폴더가 들어 있다 — 시드만 고친 변경에서도 이 테스트가 돈다. 확인은
 * 캐시를 거치는 turbo 가 아니라 이 패키지의 vitest 를 직접 돌린다(turbo 캐시 입력에 `apps/api` 가 없어 시드만 바뀌면 이전
 * 결과가 재생된다).
 */
const SEED_FILES = import.meta.glob<string>("../../../../../api/scripts/seed_content/data/tutorial/*/*.json", {
  query: "?raw",
  import: "default",
  eager: true,
});

/**
 * 시드에 같은 칸이 있지만 원고가 free 값을 쓰는 칸과 그 이유. 시드 값이 화면 글자가 아닌 칸만 둔다.
 * - 장르: 시드에는 장르 id(uuid)만 있고, 빌더가 보이는 장르 이름은 서버의 장르 목록에서 온다.
 */
const FREE_VALUE_ALLOWLIST = new Set(["registration.genre"]);

/** 백틱 네 개 이상이 필드 값에 있으면 원고의 바깥 펜스가 그 자리에서 일찍 닫힌다. */
const FENCE_BREAKING_RUN = /`{4,}/;

function normalizeNewlines(text: string): string {
  return text.replace(/\r\n/g, "\n");
}

function slugOf(filePath: string): string {
  return filePath.slice(filePath.lastIndexOf("/") + 1, -".json".length);
}

/** `startingSetups.0.prologue` 처럼 점으로 이은 경로를 따라간다. 숫자 조각은 배열 위치다. */
function resolvePath(root: unknown, path: string): unknown {
  let node = root;
  for (const key of path.split(".")) {
    if (Array.isArray(node) && /^\d+$/.test(key)) {
      node = node[Number(key)];
    } else if (isRecord(node)) {
      node = node[key];
    } else {
      return undefined;
    }
  }
  return node;
}

/** 시드 경로의 숫자 조각을 `*` 로 — 목업 표의 `seedPath` 와 같은 표기. */
function templateOf(path: string): string {
  return path.replace(/(^|\.)\d+(?=\.|$)/g, "$1*");
}

/** 경로의 배열 위치 숫자들(앞에서부터). */
function indicesOf(path: string): number[] {
  return path.split(".").flatMap((segment) => (/^\d+$/.test(segment) ? [Number(segment)] : []));
}

/** 인용 글이 시드 글의 전문이거나 연속된 온전한 줄인지. */
function isWholeLines(quote: string, value: string, { maxLines }: { maxLines?: number } = {}): boolean {
  const quoteLines = normalizeNewlines(quote).split("\n");
  const valueLines = normalizeNewlines(value).split("\n");
  if (quoteLines.every((line) => line.trim() === "")) return false;
  if (maxLines !== undefined && quoteLines.length > maxLines) return false;
  for (let start = 0; start + quoteLines.length <= valueLines.length; start += 1) {
    if (quoteLines.every((line, offset) => line === valueLines[start + offset])) return true;
  }
  return false;
}

const SEED_FILE_PATHS = Object.keys(SEED_FILES);
const SEED_BY_SLUG = new Map<string, unknown>(
  Object.entries(SEED_FILES).map(([filePath, raw]): [string, unknown] => [slugOf(filePath), JSON.parse(raw)]),
);

function seedValue(source: Extract<ExampleSource, { kind: "seed" }>): unknown {
  return resolvePath(SEED_BY_SLUG.get(source.slug), source.path);
}

type ProseQuote = {
  label: string;
  kind: ProseExampleKind;
  source: Extract<ExampleSource, { kind: "seed" }>;
  body: string;
};

function proseQuotesOf(topic: GuideTopic, manuscript: Manuscript): ProseQuote[] {
  const items: GuideItem[] = manuscript.sections.flatMap((section) =>
    section.content.flatMap((item): GuideItem[] => {
      if (item.kind === "markdown" || item.kind === "example") return [item];
      if (item.kind === "note") return [...item.intro, ...(item.details ?? [])];
      return [...item.intro, ...(item.details ?? []), ...item.bad.flatMap((part) => part.prose)];
    }),
  );
  return items.flatMap((item) =>
    item.kind === "example" && item.example.source.kind === "seed"
      ? [
          {
            label: `${topic.id} ${item.example.line}번째 줄`,
            kind: item.example.kind,
            source: item.example.source,
            body: item.example.body,
          },
        ]
      : [],
  );
}

const PARSED = GUIDE_TOPICS.map((topic) => [topic, parseManuscript(topic.manuscript)] as const);
const PROSE_QUOTES = PARSED.flatMap(([topic, manuscript]) => proseQuotesOf(topic, manuscript));

describe("tutorial seed files", () => {
  it("are found next to the API seed data", () => {
    expect(SEED_FILE_PATHS.length).toBeGreaterThan(0);
  });

  // 스토리·캐릭터 두 폴더를 slug 하나로 찾으므로 겹치면 어느 파일을 대조했는지 모호해진다.
  it("have unique slugs across story and character folders", () => {
    expect(SEED_BY_SLUG.size).toBe(SEED_FILE_PATHS.length);
  });
});

describe("guide prose seed quotes", () => {
  it("exist in the manuscripts", () => {
    expect(PROSE_QUOTES.length).toBeGreaterThan(0);
  });

  it.each(PROSE_QUOTES.map((quote) => [`${quote.label} ${quote.source.slug}:${quote.source.path}`, quote] as const))(
    "%s matches the seed text",
    (_label, quote) => {
      expect(SEED_BY_SLUG.has(quote.source.slug), `모르는 시드 slug: ${quote.source.slug}`).toBe(true);
      const value = seedValue(quote.source);
      expect(typeof value, `경로가 문자열 필드를 가리키지 않는다: ${quote.source.path}`).toBe("string");
      if (typeof value !== "string") return;
      expect(FENCE_BREAKING_RUN.test(value), "시드 문안에 백틱 네 개 이상이 있어 원고 펜스가 일찍 닫힌다").toBe(false);
      expect(isWholeLines(quote.body, value), "인용이 시드 값의 전문이나 연속된 온전한 줄이 아니다(또는 비어 있다)").toBe(true);
    },
  );

  // 채팅 예시는 말한 쪽에 따라 말풍선 자리가 갈린다. 사용자가 보내는 글(전개 예시·대화 예시의 사용자 줄, 추천 답변)을
  // 캐릭터 말풍선으로 그리거나 그 반대로 그리면 화면이 대화를 거꾸로 보여 준다.
  const CHAT_QUOTES = PROSE_QUOTES.filter((quote) => quote.kind !== "field");
  it.each(CHAT_QUOTES.map((quote) => [`${quote.label} ${quote.source.path}`, quote] as const))(
    "%s is drawn on the speaker's side",
    (_label, quote) => {
      const isUserLine = /(^|\.)(userLine|suggestedReplies\.\d+)$/.test(quote.source.path);
      expect(quote.kind).toBe(isUserLine ? "chat-user" : "chat");
    },
  );
});

// ── 칸 블록의 목업 값(스토리) ────────────────────────────────────────────────

type BlockValue = { role: "value" | "good"; value: FieldValue; blockLine: number };

const BLOCK_CASES = PARSED.flatMap(([topic, manuscript]) => {
  const mockups = topic.fieldMockups;
  if (!mockups) return [];
  return manuscript.sections.flatMap((section) =>
    section.content.flatMap((item) => (item.kind === "field" ? [{ topic, mockups, block: item }] : [])),
  );
});

describe.each(BLOCK_CASES.map((entry) => [`${entry.topic.id} ${entry.block.id}`, entry] as const))(
  "%s block",
  (_label, { mockups, block }) => {
    const values: BlockValue[] = [
      ...block.values.map((value) => ({ role: "value" as const, value, blockLine: block.line })),
      ...block.bad.flatMap((part) => (part.good ? [{ role: "good" as const, value: part.good, blockLine: block.line }] : [])),
    ];

    it("binds every seed value to its field's seed path", () => {
      const mismatched = values.flatMap(({ value }) => {
        if (value.source.kind !== "seed" || !isStoryFieldKey(value.key)) return [];
        const expected = mockups[value.key].seedPath;
        return templateOf(value.source.path) === expected ? [] : [`${value.key}: ${value.source.path} (표: ${expected})`];
      });
      expect(mismatched).toEqual([]);
    });

    // 시드에 같은 칸이 있으면 목업은 시드를 보여 준다 — free 로 쓰면 시드와 어긋나도 아무도 모른다.
    it("uses free values only for fields the seed does not have", () => {
      const free = block.values.flatMap((value) =>
        value.source.kind === "free" &&
        isStoryFieldKey(value.key) &&
        mockups[value.key].seedPath !== null &&
        !FREE_VALUE_ALLOWLIST.has(value.key)
          ? [value.key]
          : [],
      );
      expect(free).toEqual([]);
    });

    it("quotes details excerpts only from this block's fields", () => {
      const seedPaths = new Set(block.keys.flatMap((key) => (isStoryFieldKey(key) ? [mockups[key].seedPath] : [])));
      const strays = (block.details ?? []).flatMap((item) => {
        if (item.kind !== "example" || item.example.kind !== "field" || item.example.source.kind !== "seed") return [];
        return seedPaths.has(templateOf(item.example.source.path)) ? [] : [item.example.source.path];
      });
      expect(strays).toEqual([]);
    });

    // 한 블록의 목업은 카드 하나를 그린 그림이라, 값들이 같은 시드·같은 카드 위치에서 와야 한다.
    it("takes all seed values of the block from the same card", () => {
      const seeds = block.values.flatMap((value) => (value.source.kind === "seed" ? [value.source] : []));
      expect(new Set(seeds.map((source) => source.slug)).size).toBeLessThanOrEqual(1);
      const indexLists = seeds.map((source) => indicesOf(source.path));
      for (const indices of indexLists) {
        for (const other of indexLists) {
          const shared = Math.min(indices.length, other.length);
          expect(indices.slice(0, shared)).toEqual(other.slice(0, shared));
        }
      }
    });

    it.each(values.filter(({ value }) => value.source.kind === "seed").map((entry) => [`${entry.role} ${entry.value.line}번째 줄 ${entry.value.key}`, entry] as const))(
      "%s matches the seed",
      (_name, { role, value }) => {
        if (value.source.kind !== "seed" || !isStoryFieldKey(value.key)) throw new Error("seed 값만 온다");
        expect(SEED_BY_SLUG.has(value.source.slug), `모르는 시드 slug: ${value.source.slug}`).toBe(true);
        const seed = seedValue(value.source);
        const mockup = mockups[value.key];
        const parsed = parseMockupValue(mockup.kind, value.body);

        switch (parsed.kind) {
          case "text":
          case "textarea":
            expect(typeof seed, `${value.source.path} 가 글이 아니다`).toBe("string");
            if (typeof seed !== "string") return;
            expect(FENCE_BREAKING_RUN.test(seed)).toBe(false);
            expect(
              isWholeLines(parsed.text, seed, role === "good" ? { maxLines: 2 } : {}),
              "시드 값의 전문이나 연속된 온전한 줄이 아니다(좋은 쪽 발췌는 두 줄까지)",
            ).toBe(true);
            return;
          case "cardList":
            expectCardsMatchSeed(value.key, value.source.path, value.source.slug, parsed, mockups);
            return;
          case "chips":
            expect(parsed.items).toEqual(seed);
            return;
          case "statRules":
          case "statChangeRules":
            expect(parsed.rules).toEqual(seed);
            return;
          case "toggle":
          case "select":
          case "number":
          case "switch":
          case "icon":
          case "color":
            expect(parsed.value).toEqual(seed);
            return;
          case "image":
          case "mediaGrid":
            throw new Error(`${parsed.kind} 값은 시드를 인용하지 않는다`);
          default:
            throw new Error("알 수 없는 값 모양");
        }
      },
    );
  },
);

/**
 * 반복 카드 목록 값: 카드 i ↔ 시드 목록 i, 카드 수 + `more` = 시드 목록 길이. 카드 객체의 키는 목록 칸 키 아래 칸 키의
 * 끝 조각이고, 조각마다 그 칸의 시드 경로로 대조한다(글은 전문이나 첫 줄).
 */
function expectCardsMatchSeed(
  listKey: string,
  listPath: string,
  slug: string,
  value: Extract<ReturnType<typeof parseMockupValue>, { kind: "cardList" }>,
  mockups: NonNullable<GuideTopic["fieldMockups"]>,
) {
  const seedList = resolvePath(SEED_BY_SLUG.get(slug), listPath);
  expect(Array.isArray(seedList), `${listPath} 가 목록이 아니다`).toBe(true);
  if (!Array.isArray(seedList)) return;
  expect(value.cards.length + value.more, "카드 수 + more 가 시드 목록 길이와 다르다").toBe(seedList.length);

  const listTemplate = templateOf(listPath);
  value.cards.forEach((card, index) => {
    for (const [piece, pieceValue] of Object.entries(card)) {
      const pieceKey = `${listKey}.*.${piece}`;
      expect(isStoryFieldKey(pieceKey), `카드 조각 ${pieceKey} 가 라벨 상수에 없다`).toBe(true);
      if (!isStoryFieldKey(pieceKey)) continue;
      const pieceSeedPath = mockups[pieceKey].seedPath;
      expect(pieceSeedPath?.startsWith(`${listTemplate}.*.`), `카드 조각 ${pieceKey} 를 시드에서 찾을 수 없다`).toBe(true);
      if (!pieceSeedPath) continue;
      const seedPiece = resolvePath(seedList[index], pieceSeedPath.slice(listTemplate.length + ".*.".length));
      if (typeof pieceValue === "string" && typeof seedPiece === "string") {
        const firstLine = normalizeNewlines(seedPiece).split("\n")[0];
        expect([normalizeNewlines(seedPiece), firstLine], `${pieceKey}[${index}] 가 시드 전문이나 첫 줄이 아니다`).toContain(
          pieceValue,
        );
        expect(pieceValue.trim()).not.toBe("");
      } else {
        expect(pieceValue, `${pieceKey}[${index}]`).toEqual(seedPiece);
      }
    }
  });
}

// 트리거 키워드는 상시 적용이 꺼진 노트에서만 필수라, 목업이 별표를 그리려면 인용한 노트가 상시 노트가 아니어야 한다.
describe("conditionally required fields", () => {
  const triggerValues = BLOCK_CASES.flatMap(({ block }) =>
    block.values.filter((value) => value.key === "keywordNotes.*.triggerKeywords" && value.source.kind === "seed"),
  );

  it("are quoted", () => {
    expect(triggerValues.length).toBeGreaterThan(0);
  });

  it.each(triggerValues.map((value) => [value.line, value] as const))("line %s quotes a note that is not always on", (_line, value) => {
    if (value.source.kind !== "seed") return;
    const notePath = value.source.path.split(".").slice(0, -1).join(".");
    const note = resolvePath(SEED_BY_SLUG.get(value.source.slug), notePath);
    expect([undefined, false]).toContain(isRecord(note) ? note.alwaysOn : "노트가 아니다");
  });
});
