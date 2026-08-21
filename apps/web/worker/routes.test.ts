import { describe, expect, it } from "vitest";

import { isKnownRoute, KNOWN_ROUTES } from "./routes";

/**
 * 라우트 파일 목록을 저장소에서 직접 읽는다.
 *
 * `@types/node`가 없는 패키지라 `node:fs` 대신 vite가 빌드 시점에 디렉터리를 훑어 주는
 * `import.meta.glob`을 쓴다(키가 곧 파일 경로다). eager가 아니라서 모듈은 로드되지 않는다.
 */
const ROUTE_FILES = import.meta.glob("../src/routes/*.tsx");

/** `builder.$type.new.tsx` → `/builder/$type/new`, `builder.index.tsx` → `/builder`. TanStack의 파일 라우트 규칙이다. */
function toRoutePattern(filePath: string): string {
  const fileName = filePath.slice(
    filePath.lastIndexOf("/") + 1,
    -".tsx".length,
  );
  const segments = fileName.split(".");
  // 끝의 `index`는 부모 경로 그 자체를 가리키는 인덱스 라우트다(`index.tsx` → `/`,
  // `builder.index.tsx` → `/builder`).
  if (segments.at(-1) === "index") segments.pop();
  return `/${segments.join("/")}`;
}

describe("KNOWN_ROUTES", () => {
  it("src/routes의 파일 목록과 정확히 일치한다", () => {
    const fromFiles = Object.keys(ROUTE_FILES)
      // `__root.tsx`는 레이아웃이라 자기 경로가 없다.
      .filter((filePath) => !filePath.endsWith("/__root.tsx"))
      .map(toRoutePattern);

    expect([...KNOWN_ROUTES].sort()).toEqual(fromFiles.sort());
  });
});

describe("isKnownRoute", () => {
  it("정적 경로를 그대로 알아본다", () => {
    expect(isKnownRoute("/")).toBe(true);
    expect(isKnownRoute("/login")).toBe(true);
    expect(isKnownRoute("/mypage")).toBe(true);
    expect(isKnownRoute("/onboarding/google")).toBe(true);
    expect(isKnownRoute("/studio/images")).toBe(true);
    expect(isKnownRoute("/builder")).toBe(true);
  });

  it("파라미터 세그먼트는 아무 값이나 받는다", () => {
    expect(isKnownRoute("/content/character/5eed0000-0000-4000-8000-00000000")).toBe(true);
    expect(isKnownRoute("/profile/anything")).toBe(true);
    expect(isKnownRoute("/chat/42")).toBe(true);
    expect(isKnownRoute("/builder/character/new")).toBe(true);
    expect(isKnownRoute("/builder/story/draft-1")).toBe(true);
  });

  it("목록에 없는 경로는 false", () => {
    expect(isKnownRoute("/asdf")).toBe(false);
    expect(isKnownRoute("/login/extra")).toBe(false);
    expect(isKnownRoute("/content/character")).toBe(false);
    expect(isKnownRoute("/content/character/1/2")).toBe(false);
    expect(isKnownRoute("/onboarding")).toBe(false);
    expect(isKnownRoute("/builder/character")).toBe(false);
  });

  it("빈 파라미터 세그먼트는 라우트가 아니다", () => {
    expect(isKnownRoute("/content/character/")).toBe(false);
    expect(isKnownRoute("/content//abc")).toBe(false);
    expect(isKnownRoute("/profile/")).toBe(false);
  });

  it("끝 슬래시는 다른 경로다 — 같은 화면에 URL이 두 벌 생기지 않게 한다", () => {
    expect(isKnownRoute("/mypage/")).toBe(false);
  });
});
