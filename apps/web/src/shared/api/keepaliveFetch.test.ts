import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE_URL } from "./client";
import { keepaliveFetch } from "./keepaliveFetch";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("keepaliveFetch", () => {
  it("keepalive·쿠키 첨부·JSON 본문으로 API 주소에 보낸다", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await keepaliveFetch("PUT", "/novels/n1/chapters/c1/reading-position", { paragraphIndex: 3 });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE_URL}/novels/n1/chapters/c1/reading-position`, {
      method: "PUT",
      keepalive: true,
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: '{"paragraphIndex":3}',
    });
  });

  it("네트워크 실패를 삼킨다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(keepaliveFetch("PUT", "/x", {})).resolves.toBeUndefined();
  });

  it("오류 상태 응답도 던지지 않는다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 500 })));

    await expect(keepaliveFetch("PUT", "/x", {})).resolves.toBeUndefined();
  });
});
