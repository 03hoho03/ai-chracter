import type { WorkerEnv } from "./types";

const APP_SHELL_PATH = "/index.html";

/**
 * SPA 셸(index.html)을 서빙한다.
 *
 * `_worker.js`가 있으면 Pages는 모든 요청을 Worker로 보내고 `public/_redirects`의
 * `/* → /index.html 200`을 더 이상 적용하지 않는다. 딥링크·새로고침이 index.html을
 * 받게 하는 일은 이제 Worker의 몫이다.
 *
 * `status`를 404로 주면 본문은 같은 셸이라 사용자에겐 앱의 NotFound 화면이 그대로
 * 보이고, 봇에게만 404가 간다(soft 404 제거).
 */
export async function serveAppShell(
  request: Request,
  env: WorkerEnv,
  status = 200,
): Promise<Response> {
  const indexUrl = new URL(APP_SHELL_PATH, request.url);
  const response = await env.ASSETS.fetch(
    new Request(indexUrl, { headers: request.headers }),
  );

  if (response.status === status) return response;

  // ASSETS가 돌려준 Response의 헤더는 불변이라 다시 감싸야 status를 바꿀 수 있다.
  return new Response(response.body, { status, headers: response.headers });
}

/**
 * 메타를 주입하려고 셸의 **본문 문자열**을 읽는다.
 *
 * `serveAppShell`과 달리 요청 헤더를 넘기지 않는다 — 크롤러의 `accept-encoding`을 그대로
 * 넘기면 자산 서버가 압축된 본문을 돌려줄 수 있고, 그러면 `text()`가 깨진 문자열을 준다.
 */
export async function readAppShellHtml(
  request: Request,
  env: WorkerEnv,
): Promise<string> {
  const indexUrl = new URL(APP_SHELL_PATH, request.url);
  const response = await env.ASSETS.fetch(new Request(indexUrl));
  return response.text();
}
