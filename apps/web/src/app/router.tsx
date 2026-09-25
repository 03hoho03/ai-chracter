import { createRouter } from "@tanstack/react-router";

import { routeTree } from "@/routeTree.gen";

import { queryClient } from "./AppProviders";
import { captureRouterError } from "./sentry";

// `defaultOnCatch`만으로는 부족하다 — `__root.tsx`의 `errorComponent`와 같은 레벨에
// 둬야 이 콜백이 실제로 불린다(근거는 `sentry.ts`의 `captureRouterError` 주석).
export const router = createRouter({ routeTree, context: { queryClient }, defaultOnCatch: captureRouterError });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
