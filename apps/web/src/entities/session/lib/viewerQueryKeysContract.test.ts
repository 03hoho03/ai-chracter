import { describe, expect, it } from "vitest";

/**
 * 사용자별 캐시를 새로 만들고 로그아웃 정리 목록(`VIEWER_QUERY_KEYS`)에 더하는 것을 잊으면, 같은 탭에서 다음에 로그인한
 * 계정에게 앞 계정의 목록이 보인다. 그 등록은 손으로 하므로 여기서 지킨다 — `entities/<이름>/api/keys.ts` 가 내보내는
 * 키 팩토리(`export const xxxKeys`)는 전부 로그아웃 정리 파일에 나오거나, 아래 "누구에게나 같은 응답" 목록에 있어야 한다.
 *
 * 팩토리 단위 검사라 한 팩토리 안에서 공개 응답과 개인 응답이 섞인 경우(작품 키의 둘러보기·상세)는 가리지 못한다 —
 * 그 경우는 정리 파일이 어느 접두를 비우는지 `clearViewerSession.test.ts` 가 따로 본다.
 *
 * 라우트 모듈처럼 이 모듈들도 소스를 문자열로 읽는다 — 키 파일을 import 하면 이름이 아니라 값만 남는다.
 */
const KEY_FACTORY_SOURCES = import.meta.glob<string>("../../*/api/keys.ts", {
  query: "?raw",
  import: "default",
  eager: true,
});

const CLEAR_VIEWER_SESSION_SOURCE = import.meta.glob<string>("./clearViewerSession.ts", {
  query: "?raw",
  import: "default",
  eager: true,
});

/** 계정과 무관하게 같은 응답이라 계정이 바뀌어도 그대로 써도 되는 캐시, 그리고 비우는 방법이 달라 정리 함수가 따로
 * 다루는 세션. 여기 더할 때는 그 응답이 정말 로그인한 사람에 따라 달라지지 않는지 서버 라우트에서 확인한다. */
const SHARED_KEY_FACTORIES = new Set([
  "noticeKeys", // 공지
  "imageModelKeys", // 이미지 모델 목록 — 로그인이 필요하지만 응답은 계정과 무관
  "profileKeys", // 남에게도 보이는 프로필
  "legalKeys", // 약관·처리방침 판
  "sessionKeys", // 세션 — 정리 함수가 `resetQueries` 로 따로 다룬다
]);

function exportedKeyFactories(): { file: string; name: string }[] {
  return Object.entries(KEY_FACTORY_SOURCES).flatMap(([file, source]) =>
    [...source.matchAll(/^export const (\w+Keys)\b/gm)].map((match) => ({ file, name: match[1] ?? "" })),
  );
}

describe("사용자별 캐시 키 등록", () => {
  const factories = exportedKeyFactories();
  const clearSource = Object.values(CLEAR_VIEWER_SESSION_SOURCE)[0] ?? "";

  it("검사 대상을 실제로 찾았다 — glob 이 비면 아래 검사가 통째로 공회전한다", () => {
    expect(factories.length).toBeGreaterThanOrEqual(20);
    expect(clearSource).toContain("const VIEWER_QUERY_KEYS");
  });

  it.each(factories)("$name($file)은 로그아웃 정리 목록이나 공개 응답 목록에 있다", ({ name }) => {
    const isRegistered = new RegExp(`\\b${name}\\.`).test(clearSource);
    expect(isRegistered || SHARED_KEY_FACTORIES.has(name), `${name} 이 어느 목록에도 없다`).toBe(true);
  });

  it("공개 응답 목록에 적은 이름은 실제로 있는 팩토리다 — 지운 팩토리가 목록에 남아 다른 이름을 가리지 않게", () => {
    const names = new Set(factories.map((factory) => factory.name));
    for (const name of SHARED_KEY_FACTORIES) expect(names.has(name), name).toBe(true);
  });
});
