import { describe, expect, it } from "vitest";

import { GUIDE_TOPICS } from "./topics";

/**
 * 토픽 등록과 라우트 파일이 짝을 이루는지 본다. 토픽마다 개요(`guide.<id>.index.tsx`)와 단계(`guide.<id>.$step.tsx`)
 * 라우트 파일이 정확히 하나씩 있어야 한다 — 빠지면 가이드가 열리지 않고, 남으면 원고 없는 라우트가 생긴다. Worker 의 알려진
 * 경로 목록과 라우트 파일의 대조는 `worker/routes.test.ts` 가 따로 한다.
 *
 * 라우트 파일은 문자열로 읽는다 — node 환경에서 라우트 모듈을 import 하면 모듈 최상위 `localStorage` 접근에서 죽는다.
 */
const GUIDE_ROUTE_SOURCES = import.meta.glob<string>("@/routes/guide.*.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
});

const ROUTE_KINDS = {
  index: { fileSuffix: "index", routePath: (topicId: string) => `/guide/${topicId}/` },
  step: { fileSuffix: "$step", routePath: (topicId: string) => `/guide/${topicId}/$step` },
} as const;

/** `…/guide.story.$step.tsx` → `story.$step`. */
function routeNameOf(routeFilePath: string): string {
  return routeFilePath.slice(routeFilePath.lastIndexOf("/guide.") + "/guide.".length, -".tsx".length);
}

describe("GUIDE_TOPICS", () => {
  it("has exactly an overview route file and a step route file per topic", () => {
    const routeNames = Object.keys(GUIDE_ROUTE_SOURCES).map(routeNameOf).sort();
    const expected = GUIDE_TOPICS.flatMap((topic) =>
      Object.values(ROUTE_KINDS).map((kind) => `${topic.id}.${kind.fileSuffix}`),
    ).sort();
    expect(routeNames).toEqual(expected);
  });

  it("has a manuscript for every topic", () => {
    for (const topic of GUIDE_TOPICS) {
      expect(topic.manuscript.trim(), `${topic.id} 원고가 비어 있다`).not.toBe("");
    }
  });

  // 단계 페이지가 빌더 탭과 1:1 이라, 탭 목록이 비면 단계 페이지가 하나도 없다.
  it("ties every topic to its builder tabs", () => {
    expect(GUIDE_TOPICS.filter((topic) => topic.steps.length === 0).map((topic) => topic.id)).toEqual([]);
  });
});

describe("guide routes", () => {
  // 빌더에서 새 탭으로 여는 공개 페이지라 로그인 가드가 없어야 한다(로그아웃 상태에서도 열린다). 소스 글자로 보는
  // 검사라 진입 훅(`beforeLoad`)이 가드인지 다른 일인지 가리지 못한다 — 그래서 진입 훅 자체를 두지 않고, 모르는 단계
  // id 는 페이지 컴포넌트가 개요로 돌려보낸다.
  it.each(Object.entries(GUIDE_ROUTE_SOURCES))("%s is public", (_filePath, source) => {
    expect(source).not.toContain("requireSession");
    expect(source).not.toContain("beforeLoad");
  });

  it.each(Object.entries(GUIDE_ROUTE_SOURCES))("%s renders its own topic", (filePath, source) => {
    const [topicId = "", fileSuffix] = routeNameOf(filePath).split(".");
    const kind = Object.values(ROUTE_KINDS).find((candidate) => candidate.fileSuffix === fileSuffix);
    expect(kind, `모르는 가이드 라우트 파일: ${filePath}`).toBeDefined();
    if (!kind) return;
    expect(source).toContain(`createFileRoute("${kind.routePath(topicId)}")`);
    expect(source).toContain(`topicId="${topicId}"`);
  });
});
