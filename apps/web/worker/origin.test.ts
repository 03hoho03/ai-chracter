import { describe, expect, it } from "vitest";

import { resolvePublicOrigin } from "./origin";
import type { WorkerEnv } from "./workerRuntime";

const ASSETS = { fetch: () => Promise.resolve(new Response("asset")) };
const REQUEST = new Request("https://preview.pages.dev/content/character/1");

describe("resolvePublicOrigin", () => {
  it("PUBLIC_ORIGIN이 요청 host를 이긴다", () => {
    const env: WorkerEnv = { ASSETS, PUBLIC_ORIGIN: "https://ddona.example" };

    expect(resolvePublicOrigin(env, REQUEST)).toBe("https://ddona.example");
  });

  it("끝의 슬래시를 잘라낸다 — 대시보드 입력값을 신뢰하지 않는다", () => {
    const env: WorkerEnv = { ASSETS, PUBLIC_ORIGIN: "https://ddona.example/" };

    expect(resolvePublicOrigin(env, REQUEST)).toBe("https://ddona.example");
  });

  it("환경변수가 없으면 요청 오리진으로 폴백한다 (로컬 개발)", () => {
    expect(resolvePublicOrigin({ ASSETS }, REQUEST)).toBe(
      "https://preview.pages.dev",
    );
  });
});
