import { createHashHistory, createRootRoute, createRoute, createRouter, redirect } from "@tanstack/react-router";

import { parseRunDetailSearch, RunDetailPage } from "@/pages/run-detail";
import { parseRunListSearch, RunListPage } from "@/pages/run-list";
import { staticBundleState } from "@/shared/api/staticBundle";

// 라우트는 파일 기반 생성 대신 여기에 코드로 적는다. 화면이 둘뿐이고, 런 하나를 단일 HTML 파일로 굳힐 때 JS 가
// 청크로 따로 떨어지지 않게 하려는 것이다 — 라우터 플러그인의 자동 분할도, `lazy`·`lazyRouteComponent`·동적
// `import()` 도 청크를 만든다. 그래서 이 앱에서는 그것들을 쓰지 않는다.
// 루트 라우트는 화면 없이 둔다(컴포넌트가 없으면 라우터가 자식 라우트를 그대로 그린다).
const rootRoute = createRootRoute();

// 읽지 못한 정적 파일도 상세로 보낼 때 쓰는 자리 id. 상세가 실린 데이터를 읽지 못한 까닭을 보인다.
const UNREADABLE_STATIC_RUN_ID = "unreadable";

const runListRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  validateSearch: parseRunListSearch,
  // 정적 HTML 에는 런이 하나뿐이고 목록은 측정 서버가 있어야 하므로, 첫 화면(과 목록으로 가는 링크)이 그 런의 상세다.
  beforeLoad: () => {
    const state = staticBundleState();
    if (state.kind === "absent") return;
    // `throw: true` 는 redirect 가 스스로 던지게 한다 — 라우터가 잡아 옮기는 객체라 Error 가 아니다.
    redirect({
      to: "/runs/$runId",
      params: { runId: state.kind === "ready" ? state.bundle.detail.run.runId : UNREADABLE_STATIC_RUN_ID },
      replace: true,
      throw: true,
    });
  },
  component: RunListPage,
});

const runDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/runs/$runId",
  validateSearch: parseRunDetailSearch,
  component: RunDetailPage,
});

const routeTree = rootRoute.addChildren([runListRoute, runDetailRoute]);

// 해시 history 는 위치를 주소의 `#` 뒤(`#/runs/…`)에만 적고 문서 경로는 건드리지 않는다. 서버 라우팅이 없는
// `file://` 로 연 HTML 에서도 같은 라우트를 쓰려는 선택이고, dev 서버(http)에서도 같은 설정이 돌아 모드별로 나누지 않는다.
export const router = createRouter({ routeTree, history: createHashHistory() });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
