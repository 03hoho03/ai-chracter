import type { CacheLike } from "./workerRuntime";

/**
 * Workers 런타임 전역. DOM lib의 `CacheStorage`에는 `default`가 없어서 여기서만 좁혀 선언한다.
 * `declare`라 번들에는 남지 않고 런타임에는 그대로 전역 `caches`를 가리킨다.
 */
declare const caches: {
  default: {
    match(request: Request): Promise<Response | undefined>;
    put(request: Request, response: Response): Promise<void>;
  };
};

/** 진입점에서 한 번 만들어 주입하는 실제 Cache API 어댑터. */
export function createRuntimeCache(): CacheLike {
  return {
    match: (request) => caches.default.match(request),
    // `caches.default.put`은 GET이 아닌 요청에 대해 던진다("Cannot cache response to
    // non-GET request"). 크롤러는 HEAD를 보내므로 그대로 두면 Worker가 만드는 응답이
    // HEAD에서만 500이 된다 — 캐시를 조용히 건너뛰는 게 맞다.
    put: (request, response) =>
      request.method === "GET"
        ? caches.default.put(request, response)
        : Promise.resolve(),
  };
}
