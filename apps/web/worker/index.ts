import { createRuntimeCache } from "./cache";
import { handleRequest } from "./handler";
import type { WorkerEnv } from "./workerRuntime";

/**
 * Cloudflare Pages Advanced Mode 진입점. esbuild가 이 파일을 `dist/_worker.js`로 번들한다.
 *
 * 여기 있는 파일은 apps/web 빌드 출력에만 따라붙는다 — 저장소 루트의 `functions/`에 두면
 * admin Pages 프로젝트도 Root directory가 루트라 같은 서버 코드를 집어가 SPA 라우팅이 깨진다.
 */
export default {
  fetch(request: Request, env: WorkerEnv): Promise<Response> {
    return handleRequest(request, env, { cache: createRuntimeCache() });
  },
};
