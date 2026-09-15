import { init } from "@sentry/react";
import type { Breadcrumb, ErrorEvent } from "@sentry/react";

function stripQueryString(url: string): string {
  const queryIndex = url.indexOf("?");
  return queryIndex === -1 ? url : url.slice(0, queryIndex);
}

function stripBreadcrumbUrls(breadcrumb: Breadcrumb): Breadcrumb {
  const data = breadcrumb.data;
  if (data) {
    for (const key of ["url", "to", "from"] as const) {
      const value = data[key];
      if (typeof value === "string") data[key] = stripQueryString(value);
    }
  }
  return breadcrumb;
}

/**
 * API 쪽 `_strip_query_string`(core/sentry.py, MT-5)과 같은 방침 — 파라미터 이름이 아니라
 * 쿼리스트링 자체를 통째로 버린다. `@sentry/browser` 10.74.0은 PII 게이트 없이 쿼리스트링을
 * 그대로 붙인다(설치된 SDK 소스로 확인):
 * - `httpContextIntegration`(`integrations/httpcontext.js`)이 `getHttpRequestData`
 *   (`helpers.js`)로 `window.location.href`를 `request.url`에, `document.referrer`를
 *   `request.headers.Referer`에 그대로 싣는다.
 * - `breadcrumbsIntegration`(`integrations/breadcrumbs.js`)의 history 핸들러가 같은 URL을
 *   (동일 출처면 쿼리스트링이 실린 상대경로로) `breadcrumb.data.to`/`.from`에, xhr/fetch
 *   핸들러가 요청 URL을 `breadcrumb.data.url`에 남긴다.
 * `routes/reset-password.tsx`의 비밀번호 재설정 토큰과 `routes/onboarding.google.tsx`의
 * OAuth code/state가 전부 이 경로들로 실려서 세 군데 다 지운다.
 */
export function stripQueryStrings(event: ErrorEvent): ErrorEvent {
  const { request } = event;
  if (request) {
    if (typeof request.url === "string") {
      request.url = stripQueryString(request.url);
    }
    const referer = request.headers?.Referer;
    if (typeof referer === "string" && request.headers) {
      request.headers.Referer = stripQueryString(referer);
    }
  }
  event.breadcrumbs = event.breadcrumbs?.map(stripBreadcrumbUrls);
  return event;
}

/**
 * errors-only 최소 구성(monitoring-techspec.md MT-7). `browserTracingIntegration`·
 * `replayIntegration`은 어디서도 import하지 않는다 — 둘 다 기본 통합이 아니라 import해야만
 * 번들에 들어가므로, 이 파일이 그 두 이름을 쓰지 않는 것 자체가 트리셰이킹 보증이다.
 *
 * DSN이 없으면 `init`을 아예 부르지 않는다 — dev 기본 비활성(API 쪽 MT-4와 같은 원칙).
 */
export function initSentry(): void {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (!dsn) return;

  init({
    dsn,
    environment: import.meta.env.MODE,
    // 트레이싱 통합을 안 불러왔으니 지금은 이 값이 no-op이다. 그래도 명시적으로 0을 둔다 —
    // 누군가 나중에 `browserTracingIntegration`을 추가하는 순간 조용히 트레이싱이
    // 켜지지 않게 하는 방어선이다(API 쪽 MT-5가 같은 이유로 `traces_sample_rate=0`을 건다).
    tracesSampleRate: 0,
    // 자가호스팅(Bugsink)이라 Sentry SaaS의 서버측 Inbound Filters를 쓸 수 없어 SDK에서
    // 직접 거른다. 브라우저 확장이 주입한 스크립트는 여기가 아니라 `allowUrls`가 막는다 —
    // 확장 에러 메시지는 확장마다 제각각이라 문자열로 다 따라잡을 수 없지만, 확장의 스택
    // 프레임은 우리 도메인이 아닌 `chrome-extension://` 등에서 오므로 도메인 화이트리스트
    // 하나로 알려지지 않은 확장까지 함께 막힌다.
    ignoreErrors: [
      // fetch abort — 사용자가 페이지를 떠나거나 다음 요청이 이전 요청을 취소할 때 흔하다.
      "AbortError",
      // Vite 동적 import 실패 — 배포 직후 캐시된 페이지가 이미 사라진 청크를 요청할 때 흔하다.
      /Failed to fetch dynamically imported module/,
      /error loading dynamically imported module/,
    ],
    allowUrls: [
      /^https:\/\/ddona\.site\//,
      /^https:\/\/[a-z0-9-]+\.ai-character-chat-web\.pages\.dev\//,
    ],
    beforeSend: stripQueryStrings,
    beforeBreadcrumb(breadcrumb) {
      // 클릭 breadcrumb은 클릭한 요소의 텍스트를 담는다 — 채팅 화면에서 그건 메시지 본문이다.
      if (breadcrumb.category === "ui.click") return null;
      return breadcrumb;
    },
  });
}
