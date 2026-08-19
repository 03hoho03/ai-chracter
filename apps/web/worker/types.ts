/** Pages Advanced Mode(`dist/_worker.js`)에서 Worker가 받는 바인딩과 환경변수. */
export interface WorkerEnv {
  /** 빌드 산출물(`dist/`)을 서빙하는 Pages 기본 바인딩. */
  ASSETS: { fetch(request: Request): Promise<Response> };
  /**
   * 백엔드 API의 오리진. Pages 대시보드의 **런타임** 환경변수라
   * 빌드타임 `VITE_API_BASE_URL`과는 별개로 설정해야 한다.
   * 없으면 SEO 경로를 통째로 건너뛴다(`handleRequest` 참고).
   */
  API_BASE_URL?: string;
}

/**
 * Cache API에서 실제로 쓰는 두 메서드만 노출하는 어댑터.
 *
 * Workers 런타임의 `caches.default`는 Node에 없어서 핸들러가 직접 참조하면
 * vitest(`environment: "node"`)에서 그 경로 전체가 테스트 불가능해진다.
 * 그래서 캐시는 항상 이 인터페이스로만 다루고 진입점에서 주입한다.
 */
export interface CacheLike {
  match(request: Request): Promise<Response | undefined>;
  put(request: Request, response: Response): Promise<void>;
}

/** 런타임에서만 만들 수 있는 것들을 핸들러에 주입하는 통로. */
export interface WorkerDeps {
  cache: CacheLike;
}
