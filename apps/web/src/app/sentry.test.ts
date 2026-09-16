import { addBreadcrumb, captureException, flush, httpContextIntegration, init, linkedErrorsIntegration } from "@sentry/react";
import type { Breadcrumb, ErrorEvent } from "@sentry/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { captureRouterError, stripQueryStrings } from "./sentry";

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

describe("captureRouterError", () => {
  // ⚠️ 이 테스트가 증명하는 것: `captureRouterError(error, errorInfo)`를 직접 호출하면
  // Sentry 이벤트가 나가고 그 안에 componentStack이 실린다는 것. **증명하지 못하는 것**:
  // TanStack Router가 실제로 이 함수를 불러준다는 배선 자체(`router.tsx`의 `defaultOnCatch` +
  // `__root.tsx`의 `errorComponent`) — `RouterProvider`를 마운트해야 확인되는데, 이 저장소
  // vitest는 `environment: "node"`이고 jsdom/@testing-library가 없어(`apps/web/CLAUDE.md`
  // 검증 워크플로) 그런 통합 테스트를 여기서 만들지 않는다. 그 배선은 브라우저 실측 몫이다.
  it("componentStack을 실어 이벤트를 보낸다", async () => {
    const sentEvents: ErrorEvent[] = [];
    init({
      dsn: "https://public@o0.ingest.example.com/1",
      // linkedErrorsIntegration만 있으면 충분하다 — `captureReactException`(@sentry/react
      // error.js)이 componentStack을 원본 에러의 `cause`(합성 에러, `.stack`에
      // componentStack을 그대로 담음)로 심고, 그 `cause`를 별도 exception 항목으로 이벤트에
      // 붙이는 게 linkedErrorsIntegration의 일이다(설치된 @sentry/core 10.74.0
      // integrations/linkederrors.js로 확인). 나머지 기본 통합은 DOM을 건드려 node
      // 환경에서 불필요하다.
      defaultIntegrations: [],
      integrations: [linkedErrorsIntegration()],
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

    captureRouterError(new Error("렌더 실패"), {
      componentStack: "\n    at ChatRoomPage\n    at RootComponent",
    });
    await flush(2000);

    expect(sentEvents).toHaveLength(1);
    const [event] = sentEvents;

    // Sentry 공식 `<ErrorBoundary>`(errorboundary.js)의 componentDidCatch와 같은 경로로
    // 만들어지는 항목이라 이름이 `React ErrorBoundary ${error.name}`으로 고정돼 있다.
    const boundaryException = event?.exception?.values?.find((value) =>
      value.type?.startsWith("React ErrorBoundary"),
    );
    expect(boundaryException).toBeDefined();

    // componentStack의 각 줄이 stacktrace 프레임으로 파싱돼 실렸는지 — 어느 컴포넌트에서
    // 터졌는지가 이 계측의 핵심이므로 값이 실제로 도착했는지까지 확인한다.
    const frameFilenames = boundaryException?.stacktrace?.frames?.map((frame) => frame.filename) ?? [];
    expect(frameFilenames).toContain("ChatRoomPage");
    expect(frameFilenames).toContain("RootComponent");
  });
});
