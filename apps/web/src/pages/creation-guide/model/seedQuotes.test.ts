import { describe, expect, it } from "vitest";

import { GUIDE_TOPICS } from "../config/topics";
import { parseManuscript } from "./parseManuscript";

/**
 * 원고의 예시 인용이 튜토리얼 시드 JSON 과 글자까지 같은지 대조한다. 같은 글이 시드와 원고 두 곳에 있어
 * 한쪽만 고쳐지면 가이드가 실제 예시 작품과 다른 글을 보여 주게 된다.
 *
 * 예시 블록 여는 줄의 `seed=<slug>:<JSON 경로>` 가 가리키는 필드에 블록 본문이 부분 문자열로 들어 있어야
 * 한다(전문 인용과 발췌 인용이 같은 규칙이다). 줄바꿈 `\r\n` 만 `\n` 으로 맞추고 다른 정규화는 하지 않는다.
 *
 * 시드 JSON 은 이 테스트 파일 안에서만 읽는다. 앱 코드 모듈로 옮기면 시드 본문이 운영 번들에 실린다.
 * 파일이 앱 밖(`apps/api`)에 있어 `web` CI 의 경로 필터에 그 폴더가 들어 있다 — 시드만 고친 변경에서도
 * 이 테스트가 돈다. 확인은 캐시를 거치는 turbo 가 아니라 이 패키지의 vitest 를 직접 돌린다(turbo 캐시
 * 입력에 `apps/api` 가 없어 시드만 바뀌면 이전 결과가 재생된다).
 */
const SEED_FILES = import.meta.glob<string>("../../../../../api/scripts/seed_content/data/tutorial/*/*.json", {
  query: "?raw",
  import: "default",
  eager: true,
});

/** 백틱 네 개 이상이 필드 값에 있으면 원고의 바깥 펜스가 그 자리에서 일찍 닫힌다. */
const FENCE_BREAKING_RUN = /`{4,}/;

function normalizeNewlines(text: string): string {
  return text.replace(/\r\n/g, "\n");
}

function slugOf(filePath: string): string {
  return filePath.slice(filePath.lastIndexOf("/") + 1, -".json".length);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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

const SEED_FILE_PATHS = Object.keys(SEED_FILES);
const SEED_BY_SLUG = new Map<string, unknown>(
  Object.entries(SEED_FILES).map(([filePath, raw]): [string, unknown] => [slugOf(filePath), JSON.parse(raw)]),
);

type SeedQuote = { topicId: string; slug: string; path: string; body: string };

const SEED_QUOTES: SeedQuote[] = GUIDE_TOPICS.flatMap((topic) =>
  parseManuscript(topic.manuscript).segments.flatMap((segment) =>
    segment.kind === "example" && segment.source.kind === "seed"
      ? [{ topicId: topic.id, slug: segment.source.slug, path: segment.source.path, body: segment.body }]
      : [],
  ),
);

describe("tutorial seed files", () => {
  it("are found next to the API seed data", () => {
    expect(SEED_FILE_PATHS.length).toBeGreaterThan(0);
  });

  // 스토리·캐릭터 두 폴더를 slug 하나로 찾으므로 겹치면 어느 파일을 대조했는지 모호해진다.
  it("have unique slugs across story and character folders", () => {
    expect(SEED_BY_SLUG.size).toBe(SEED_FILE_PATHS.length);
  });
});

describe("guide seed quotes", () => {
  it("exist in the manuscripts", () => {
    expect(SEED_QUOTES.length).toBeGreaterThan(0);
  });

  it.each(SEED_QUOTES.map((quote) => [`${quote.topicId} ${quote.slug}:${quote.path}`, quote] as const))(
    "%s matches the seed text",
    (_label, quote) => {
      expect(SEED_BY_SLUG.has(quote.slug), `모르는 시드 slug: ${quote.slug}`).toBe(true);

      const value = resolvePath(SEED_BY_SLUG.get(quote.slug), quote.path);
      expect(typeof value, `경로가 문자열 필드를 가리키지 않는다: ${quote.path}`).toBe("string");
      if (typeof value !== "string") return;

      expect(FENCE_BREAKING_RUN.test(value), "시드 문안에 백틱 네 개 이상이 있어 원고 펜스가 일찍 닫힌다").toBe(
        false,
      );
      const body = normalizeNewlines(quote.body);
      expect(body, "인용 블록이 비어 있다").not.toBe("");
      expect(normalizeNewlines(value)).toContain(body);
    },
  );
});
