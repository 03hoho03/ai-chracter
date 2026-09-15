import { addBreadcrumb, captureException, flush, httpContextIntegration, init } from "@sentry/react";
import type { Breadcrumb, ErrorEvent } from "@sentry/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { stripQueryStrings } from "./sentry";

const SECRET = "reset-token-abc123";
const PAGE_URL = `https://ddona.site/reset-password?token=${SECRET}`;

describe("stripQueryStrings", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("SDK가 실제로 만드는 이벤트에서 토큰이 든 쿼리스트링을 전부 지운다", async () => {
    // httpContextIntegration은 WINDOW.document.location.href / WINDOW.document.referrer를
    // 그대로 읽는다(@sentry/browser 10.74.0 integrations/httpcontext.js의 getHttpRequestData,
    // helpers.js에서 설치된 패키지 소스로 확인).
    vi.stubGlobal("document", {
      location: { href: PAGE_URL },
      referrer: PAGE_URL,
      // BrowserClient의 생성자가 무조건 등록한다(visibilitychange 리스너, 통합과 무관).
      addEventListener: () => {},
    });

    const sentEvents: ErrorEvent[] = [];
    init({
      dsn: "https://public@o0.ingest.example.com/1",
      // 기본 통합(콘솔·DOM 클릭·xhr/fetch/history 패치 등)은 jsdom 없는 node 환경에서 굳이
      // 켤 필요가 없다 — 이 테스트가 검증할 대상인 httpContextIntegration만 남긴다.
      defaultIntegrations: [],
      integrations: [httpContextIntegration()],
      beforeSend: stripQueryStrings,
      transport: () => ({
        send(envelope) {
          for (const item of envelope[1]) {
            const [itemHeader, payload] = item;
            if (itemHeader.type === "event") {
              sentEvents.push(payload as ErrorEvent);
            }
          }
          return Promise.resolve({});
        },
        flush: () => Promise.resolve(true),
      }),
    });

    // breadcrumbsIntegration의 history/xhr 핸들러가 실제로 만드는 것과 같은 모양
    // (integrations/breadcrumbs.js의 _getHistoryBreadcrumbHandler/_getXhrBreadcrumbHandler
    // 확인 — 동일 출처 navigation은 쿼리스트링 포함 상대경로를 to/from에, xhr는 요청
    // URL을 data.url에 남긴다).
    const navigationBreadcrumb: Breadcrumb = {
      category: "navigation",
      data: { from: `/reset-password?token=${SECRET}`, to: "/login" },
    };
    const xhrBreadcrumb: Breadcrumb = {
      category: "xhr",
      type: "http",
      data: {
        method: "GET",
        url: `https://api.ddona.site/auth/password-reset/validate?token=${SECRET}`,
        status_code: 200,
      },
    };
    addBreadcrumb(navigationBreadcrumb);
    addBreadcrumb(xhrBreadcrumb);

    captureException(new Error("boom"));
    await flush(2000);

    expect(sentEvents).toHaveLength(1);
    const [event] = sentEvents;

    // request.url — window.location.href가 통째로 실리는 자리.
    expect(event?.request?.url).not.toContain("?");
    expect(event?.request?.url).not.toContain(SECRET);

    // request.headers.Referer — document.referrer가 실리는 자리.
    expect(event?.request?.headers?.Referer).not.toContain("?");
    expect(event?.request?.headers?.Referer).not.toContain(SECRET);

    // breadcrumbs — navigation의 to/from, xhr의 url.
    const breadcrumbs = event?.breadcrumbs ?? [];
    expect(breadcrumbs.length).toBeGreaterThan(0);
    for (const breadcrumb of breadcrumbs) {
      expect(JSON.stringify(breadcrumb.data)).not.toContain("?");
    }

    // 어느 필드든 토큰 값 자체가 남아 있으면 안 된다 — 전체 이벤트를 대상으로 한 번 더 확인.
    expect(JSON.stringify(event)).not.toContain(SECRET);
  });
});
