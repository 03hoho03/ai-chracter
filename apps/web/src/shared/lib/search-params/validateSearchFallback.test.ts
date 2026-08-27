import { describe, expect, it } from "vitest";

/**
 * `validateSearch`에 넘기는 zod 스키마의 **모든 필드**는 `.catch(...)`로 끝나야 한다.
 *
 * 하나라도 빠지면 그 파라미터 값이 어긋난 URL(오래된 링크·손으로 고친 주소·`?q=1`처럼 라우터가
 * 숫자로 파싱하는 값)에서 라우터가 `SearchParamError`를 던지고 `CatchBoundary`로 빠져 **화면에
 * 아무것도 안 남는다**. 축 하나가 기본값으로 떨어지는 것과 페이지가 통째로 죽는 것은 비교 대상이 아니다.
 *
 * 라우트 모듈을 직접 import해 스키마를 꺼내지 못하는 이유: vitest 환경이 `node`라 페이지 컴포넌트가
 * 딸려 오면서 모듈 최상위의 `localStorage` 접근(`shared/model/theme.ts`)에서 죽는다. 그래서 소스를
 * 문자열로 읽어 검사한다.
 */
const ROUTE_SOURCES = import.meta.glob("../../../routes/*.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** 라우트 밖에 사는 서치 스키마(`/my`의 `myWorksSearchSchema`)를 찾기 위한 두 번째 후보 목록. */
const MODEL_SOURCES = import.meta.glob("../../../pages/**/model/*.ts", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const ALL_SOURCES = { ...ROUTE_SOURCES, ...MODEL_SOURCES };

/** `const <name> = z.object({ ... })`의 중괄호 안쪽을 꺼낸다. 못 찾으면 null. */
function findSchemaBody(name: string): string | null {
  const marker = `const ${name} = z.object({`;

  for (const source of Object.values(ALL_SOURCES)) {
    const markerIndex = source.indexOf(marker);
    if (markerIndex === -1) continue;

    const start = markerIndex + marker.length;
    let depth = 1;

    for (let i = start; i < source.length; i++) {
      const char = source[i];
      if (char === "{") depth += 1;
      if (char === "}") depth -= 1;
      if (depth === 0) return source.slice(start, i);
    }
  }

  return null;
}

/** 스키마 본문에서 최상위 필드 선언 줄만 고른다(`  type: z.enum(...)...,`). */
function fieldLines(body: string): string[] {
  return body.split("\n").filter((line) => /^\s{2}\w+:\s*z\./.test(line));
}

const routesWithValidateSearch = Object.entries(ROUTE_SOURCES)
  .map(([path, source]) => ({ path, schemaName: /validateSearch:\s*(\w+)/.exec(source)?.[1] }))
  .filter((route): route is { path: string; schemaName: string } => route.schemaName !== undefined);

describe("validateSearch 스키마 규약", () => {
  it("검사 대상을 실제로 찾았다 — glob이 0건이면 아래 검사가 통째로 공회전한다", () => {
    expect(routesWithValidateSearch.length).toBeGreaterThanOrEqual(8);
  });

  it.each(routesWithValidateSearch)("$path 의 모든 필드가 .catch()로 끝난다", ({ schemaName }) => {
    const body = findSchemaBody(schemaName);
    // 스키마를 못 찾으면 조용히 통과하는 게 아니라 실패해야 한다 — 그게 이 테스트의 유일한 공회전 경로다.
    expect(body, `${schemaName} 정의를 찾지 못했다`).not.toBeNull();

    const fields = fieldLines(body ?? "");
    expect(fields.length, `${schemaName}에 필드가 없다`).toBeGreaterThan(0);

    for (const field of fields) {
      expect(field, `${schemaName}: ${field.trim()}`).toContain(".catch(");
    }
  });
});
