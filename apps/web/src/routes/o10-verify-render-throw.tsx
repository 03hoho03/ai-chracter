import { createFileRoute } from "@tanstack/react-router";

// ⚠️ 임시 라우트 — O-10(렌더 에러가 Bugsink에 안 도달하던 문제, PR #33/6991b3e) 종단 검증용.
// 2026-09-16 추가. 프로덕션에서 인위적 렌더 에러를 안전하게 일으킬 방법이 없어(fetch 패치는
// 인증 가드의 redirect()에 막히고, Array.prototype.map 패치는 렌더 밖에서 소진됨) 이 라우트로
// 직접 렌더 중 throw해 __root.tsx의 errorComponent + router.tsx의 defaultOnCatch(captureRouterError)
// 경로가 프로덕션에서 실제로 Bugsink까지 도달하는지 확인한다.
//
// 다른 페이지에서 링크하지 않는다(우연한 접근 방지). Bugsink에서 도달을 확인하면
// **이 커밋을 즉시 revert한다** — 프로덕션에 영구히 남으면 안 되는 크래시 라우트다.
export const Route = createFileRoute("/o10-verify-render-throw")({
  component: TempO10VerifyComponent,
});

// 이벤트 핸들러나 useEffect 안에서 던지면 globalHandlersIntegration이 잡아버려 이번에
// 검증하려는 CatchBoundary 경로(라우터 errorComponent → defaultOnCatch)를 타지 않는다.
// 그래서 컴포넌트 렌더 본문에서 동기적으로 throw한다.
function TempO10VerifyComponent(): never {
  throw new Error(`O10-prod-verify-${Date.now()}`);
}
