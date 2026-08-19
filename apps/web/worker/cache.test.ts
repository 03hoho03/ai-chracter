import { describe, expect, it, vi } from "vitest";

import { createRuntimeCache } from "./cache";

describe("createRuntimeCache", () => {
  it("match/put을 런타임 caches.default로 위임한다", async () => {
    const match = vi.fn(() => Promise.resolve(undefined));
    const put = vi.fn(() => Promise.resolve());
    // Node에는 caches 전역이 없다 — 주입 구조가 실제로 통하는지 여기서만 확인한다.
    Object.assign(globalThis, { caches: { default: { match, put } } });
    const request = new Request("https://ddona.example/sitemap.xml");
    const response = new Response("<urlset />");

    const cache = createRuntimeCache();
    await cache.match(request);
    await cache.put(request, response);

    expect(match).toHaveBeenCalledWith(request);
    expect(put).toHaveBeenCalledWith(request, response);
  });

  it("GET이 아닌 요청은 put하지 않는다 — 런타임이 던져 HEAD가 500이 된다", async () => {
    const put = vi.fn(() => Promise.resolve());
    Object.assign(globalThis, {
      caches: { default: { match: () => Promise.resolve(undefined), put } },
    });

    await createRuntimeCache().put(
      new Request("https://ddona.example/sitemap.xml", { method: "HEAD" }),
      new Response("<urlset />"),
    );

    expect(put).not.toHaveBeenCalled();
  });
});
