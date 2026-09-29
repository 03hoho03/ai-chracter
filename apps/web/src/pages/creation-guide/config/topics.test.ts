import { describe, expect, it } from "vitest";

import { GUIDE_TOPICS } from "./topics";

/**
 * 토픽 등록과 라우트 파일이 짝을 이루는지 본다. 토픽을 더하고 라우트 파일을 빠뜨리면(또는 반대면) 가이드가
 * 열리지 않거나 원고 없는 라우트가 생긴다. Worker 의 알려진 경로 목록과 라우트 파일의 대조는
 * `worker/routes.test.ts` 가 따로 한다.
 *
 * 라우트 파일은 문자열로 읽는다 — node 환경에서 라우트 모듈을 import 하면 모듈 최상위 `localStorage`
 * 접근에서 죽는다.
 */
const GUIDE_ROUTE_SOURCES = import.meta.glob<string>("@/routes/guide.*.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
});

function topicIdOf(routeFilePath: string): string {
  return routeFilePath.slice(routeFilePath.lastIndexOf("/guide.") + "/guide.".length, -".tsx".length);
}

describe("GUIDE_TOPICS", () => {
  it("has exactly one route file per topic", () => {
    const routeTopicIds = Object.keys(GUIDE_ROUTE_SOURCES).map(topicIdOf).sort();
    const topicIds = GUIDE_TOPICS.map((topic) => topic.id).sort();
    expect(routeTopicIds).toEqual(topicIds);
  });

  it("has a manuscript for every topic", () => {
    for (const topic of GUIDE_TOPICS) {
      expect(topic.manuscript.trim(), `${topic.id} 원고가 비어 있다`).not.toBe("");
    }
  });

  // `steps` 가 빠지면 원고의 탭 순서 검사가 조용히 건너뛰어진다. 빌더와 짝이 없는 토픽을 더할 때만 여기에
  // 그 id 를 적는다.
  it("ties every current topic to its builder tabs", () => {
    const topicsWithoutSteps = GUIDE_TOPICS.filter((topic) => !topic.steps).map((topic) => topic.id);
    expect(topicsWithoutSteps).toEqual([]);
  });
});

describe("guide routes", () => {
  // 빌더에서 새 탭으로 여는 공개 페이지라 로그인 가드가 없어야 한다(로그아웃 상태에서도 열린다).
  it.each(Object.entries(GUIDE_ROUTE_SOURCES))("%s is public", (_filePath, source) => {
    expect(source).not.toContain("requireSession");
    expect(source).not.toContain("beforeLoad");
  });

  it.each(Object.entries(GUIDE_ROUTE_SOURCES))("%s renders its own topic", (filePath, source) => {
    const topicId = topicIdOf(filePath);
    expect(source).toContain(`createFileRoute("/guide/${topicId}")`);
    expect(source).toContain(`topicId="${topicId}"`);
  });
});
