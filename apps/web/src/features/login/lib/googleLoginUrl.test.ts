import { afterEach, describe, expect, it, vi } from "vitest";

/** `apiBaseUrl`은 모듈 로드 시점에 `import.meta.env`에서 확정되므로,
 * base를 바꿔가며 검증하려면 매번 모듈을 새로 import해야 한다. */
async function buildWith(base: string, redirectTo?: string): Promise<string> {
  vi.stubEnv("VITE_API_BASE_URL", base);
  vi.resetModules();
  const { buildGoogleLoginUrl } = await import("./googleLoginUrl");
  return buildGoogleLoginUrl(redirectTo);
}

describe("buildGoogleLoginUrl", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("경로 없는 base에 /auth/google을 붙인다", async () => {
    expect(await buildWith("http://localhost:8000")).toBe("http://localhost:8000/auth/google");
  });

  it("base의 경로를 버리지 않는다 (tailscale serve의 /api 등)", async () => {
    expect(await buildWith("https://host.ts.net/api")).toBe("https://host.ts.net/api/auth/google");
  });

  it("base의 트레일링 슬래시로 //auth/google을 만들지 않는다", async () => {
    expect(await buildWith("https://api.run.app/")).toBe("https://api.run.app/auth/google");
  });

  it("redirectTo를 검색 파라미터로 붙인다", async () => {
    expect(await buildWith("https://host.ts.net/api", "/chat/1")).toBe(
      "https://host.ts.net/api/auth/google?redirect=%2Fchat%2F1",
    );
  });
});
