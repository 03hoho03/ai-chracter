import { lazy, Suspense, type ComponentProps } from "react";

import type { NovelBoardCanvas as NovelBoardCanvasComponent } from "./NovelBoardCanvas";

// 캔버스 라이브러리(`@xyflow/react`)와 그 스타일은 캔버스를 처음 그릴 때 내려받는다. 이 파일은 그 모듈을 동적으로만
// 가져오므로, 좁은 화면(흐름 목록)과 다른 화면의 번들에는 캔버스 라이브러리가 실리지 않는다.
const NovelBoardCanvas = lazy(() => import("./NovelBoardCanvas").then((module) => ({ default: module.NovelBoardCanvas })));

/** 캔버스를 처음 쓸 때 내려받는다. 받는 동안은 화 카드 모양 막대 셋 — 진행 표시라 동작 줄이기 설정에서도
 * 깜빡인다(멈추면 멈춘 화면으로 읽힌다). */
export function LazyNovelBoardCanvas(props: ComponentProps<typeof NovelBoardCanvasComponent>) {
  return (
    <Suspense fallback={<NovelBoardCanvasSkeleton />}>
      <NovelBoardCanvas {...props} />
    </Suspense>
  );
}

/** 캔버스 자리의 로딩 모양. 데이터를 기다릴 때(페이지)와 캔버스 모듈을 기다릴 때가 같은 모양이다. */
export function NovelBoardCanvasSkeleton() {
  return (
    <div role="status" className="flex size-full flex-col items-center gap-6 overflow-hidden pt-16">
      <span className="sr-only">보드를 불러오는 중이에요.</span>
      <div className="h-30 w-60 animate-pulse rounded-xl bg-muted" />
      <div className="h-30 w-60 animate-pulse rounded-xl bg-muted" />
      <div className="h-30 w-60 animate-pulse rounded-xl bg-muted" />
    </div>
  );
}
