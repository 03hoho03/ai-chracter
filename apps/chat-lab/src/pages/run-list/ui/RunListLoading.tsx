import { cn } from "@/shared/lib/cn";

const SKELETON_ROWS = 12;

/** 빈 막대 길이 — 행마다 조금씩 달라야 표처럼 읽힌다. */
const BAR_WIDTHS = ["w-2/5", "w-3/5", "w-1/2", "w-4/5", "w-2/3", "w-3/4"] as const;

/**
 * 첫 목록을 기다리는 동안 — 본문 뼈대를 그대로 두고 칸 자리에 빈 막대를 둔다. 진행은 움직이는 막대가 아니라 지난 초로 보인다.
 * 처음 부를 때 측정 서버가 런 루트를 훑고 묶음을 하나씩 열어 수십 초 걸리기 때문이다.
 */
export function RunListLoading({ seconds }: { seconds: number }) {
  return (
    <div className="grid h-full grid-cols-1 lg:grid-cols-run-list xl:grid-cols-run-list-wide">
      <div className="hidden border-r border-border bg-surface lg:block">
        <div className="h-8 border-b border-border" />
        <SkeletonBars count={6} />
      </div>
      <div className="min-h-0 bg-surface">
        <div role="status" className="flex h-8 items-center gap-2 border-b border-border px-3 text-data text-ink-secondary">
          런 목록을 불러오는 중이다. 처음 부르면 측정 서버가 런 루트를 훑어 수십 초 걸린다.
          <span aria-hidden="true" className="ml-auto shrink-0 tabular-nums text-ink-muted">
            {seconds}초
          </span>
        </div>
        <SkeletonBars count={SKELETON_ROWS} />
      </div>
      <div className="hidden border-l border-border bg-surface xl:block">
        <div className="h-8 border-b border-border" />
      </div>
    </div>
  );
}

function SkeletonBars({ count }: { count: number }) {
  return (
    <ul aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        // 정적인 빈 자리라 순서가 바뀌지 않는다.
        <li key={index} className="flex h-7 items-center border-b border-border px-3">
          <span className={cn("h-2 rounded-sm bg-surface-raised", BAR_WIDTHS[index % BAR_WIDTHS.length])} />
        </li>
      ))}
    </ul>
  );
}
