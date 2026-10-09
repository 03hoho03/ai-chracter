import { lazy, Suspense, type ComponentProps } from "react";

// 비교 라이브러리(`diff`)는 판·버전 비교를 열 때만 내려받는다. 이 파일은 그 모듈을 동적으로만 가져오므로, 앱 루트에
// 늘 마운트된 모달이 이 파일을 정적으로 가져와도 첫 화면 번들에 비교 라이브러리가 실리지 않는다.
const DiffView = lazy(() => import("./text-diff").then((module) => ({ default: module.DiffView })));

type LazyDiffViewProps = ComponentProps<typeof DiffView>;

/** `DiffView` 를 처음 쓸 때 내려받는다. 받는 동안은 문단 모양 막대를 보인다 — 진행 표시라 동작 줄이기 설정에서도
 * 깜빡인다(멈추면 멈춘 화면으로 읽힌다). 모달 표면 위에 놓이므로 막대는 `secondary` 다(`muted` 는 그 표면과 같은
 * 값이라 사라진다). */
export function LazyDiffView(props: LazyDiffViewProps) {
  return (
    <Suspense fallback={<DiffViewSkeleton />}>
      <DiffView {...props} />
    </Suspense>
  );
}

function DiffViewSkeleton() {
  return (
    <div role="status" className="flex flex-col gap-2">
      <span className="sr-only">비교를 불러오는 중이에요.</span>
      <div className="h-4 w-1/3 animate-pulse rounded bg-secondary" />
      <div className="h-16 animate-pulse rounded-lg bg-secondary" />
      <div className="h-10 animate-pulse rounded-lg bg-secondary" />
    </div>
  );
}
