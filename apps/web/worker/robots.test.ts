import { describe, expect, it } from "vitest";

import { buildRobotsTxt, handleRobots } from "./robots";
import type { WorkerEnv } from "./workerRuntime";

const ASSETS = { fetch: () => Promise.resolve(new Response("asset")) };

describe("buildRobotsTxt", () => {
  it("Sitemap 라인이 인자로 받은 오리진 기준 절대 URL이다", () => {
    expect(buildRobotsTxt("https://ddona.example")).toContain(
      "Sitemap: https://ddona.example/sitemap.xml",
    );
  });

  it("모든 크롤러에 같은 규칙을 준다", () => {
    expect(buildRobotsTxt("https://ddona.example").split("\n")[0]).toBe(
      "User-agent: *",
    );
  });

  it.each([
    "/login",
    "/signup",
    "/forgot-password",
    "/reset-password",
    "/onboarding/",
    "/mypage",
    "/favorites",
    "/chats",
    "/chat/",
    "/builder/",
    "/studio/",
    "/ui-demo",
  ])("%s를 Disallow 한다", (path) => {
    expect(buildRobotsTxt("https://ddona.example").split("\n")).toContain(
      `Disallow: ${path}`,
    );
  });

  it("공개 경로는 막지 않는다 — 홈과 콘텐츠 상세가 색인 대상이다", () => {
    const disallowed = buildRobotsTxt("https://ddona.example")
      .split("\n")
      .filter((line) => line.startsWith("Disallow:"));

    expect(disallowed).not.toContain("Disallow: /");
    expect(disallowed.some((line) => line.includes("/content"))).toBe(false);
    expect(disallowed.some((line) => line.includes("/profile"))).toBe(false);
  });
});

describe("handleRobots", () => {
  it("text/plain으로 응답한다", async () => {
    const env: WorkerEnv = { ASSETS, PUBLIC_ORIGIN: "https://ddona.example" };

    const response = handleRobots(new Request("https://ddona.example/robots.txt"), env);

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("text/plain; charset=utf-8");
    expect(await response.text()).toContain("Sitemap: https://ddona.example/sitemap.xml");
  });

  it("프리뷰 host에서 요청해도 Sitemap은 PUBLIC_ORIGIN을 가리킨다", async () => {
    const env: WorkerEnv = { ASSETS, PUBLIC_ORIGIN: "https://ddona.example" };

    const response = handleRobots(
      new Request("https://preview.pages.dev/robots.txt"),
      env,
    );

    expect(await response.text()).toContain("Sitemap: https://ddona.example/sitemap.xml");
  });
});
