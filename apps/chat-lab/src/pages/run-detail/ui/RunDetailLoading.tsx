import { cn } from "@/shared/lib/cn";

/** 턴 목록 자리의 빈 행 수 — 행이 두 줄(44px)이라, 한 줄 행 14개가 채우던 높이를 9행이 채운다. */
const SKELETON_ROWS = 9;

/** 빈 막대 길이 — 행마다 조금씩 달라야 목록처럼 읽힌다. */
const BAR_WIDTHS = ["w-2/5", "w-3/5", "w-1/2", "w-4/5", "w-2/3", "w-3/4"] as const;

/**
 * 런 상세를 기다리는 동안 — 작업대 뼈대(타임라인 띠·턴 목록·대화·검사기)를 그대로 두고 칸 자리에 빈 막대를 둔다. 진행은 움직이는
 * 막대가 아니라 지난 초로 보인다. 측정 서버가 묶음을 처음 열 때(덤프·턴 기록을 읽어 잇는다) 몇 초가 걸릴 수 있다.
 */
export function RunDetailLoading({ seconds }: { seconds: number }) {
  return (
    <div className="flex h-full flex-col">
      <div className="h-16 shrink-0 border-b border-border bg-surface" />
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-run-detail xl:grid-cols-run-detail-wide">
        <div className="hidden border-r border-border bg-surface lg:block">
          <div className="h-8 border-b border-border" />
          <TurnSkeletonRows count={SKELETON_ROWS} />
        </div>
        <div className="min-h-0 bg-surface">
          <div role="status" className="flex h-8 items-center gap-2 border-b border-border px-3 text-data text-ink-secondary">
            런을 여는 중이다. 측정 서버가 드라이버 로그·덤프·턴 기록을 턴 단위로 잇는다.
            <span aria-hidden="true" className="ml-auto shrink-0 tabular-nums text-ink-muted">
              {seconds}초
            </span>
          </div>
          <SkeletonBars count={6} />
        </div>
        <div className="hidden border-l border-border bg-surface xl:block">
          <div className="h-8 border-b border-border" />
        </div>
      </div>
    </div>
  );
}

/** 턴 목록 자리 — 턴 목록 행처럼 두 줄(발화 · 응답)에 같은 높이, 막대도 발화 칸이 시작하는 자리에서 시작한다. */
function TurnSkeletonRows({ count }: { count: number }) {
  return (
    <ul aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        // 정적인 빈 자리라 순서가 바뀌지 않는다.
        <li key={index} className="flex h-11 flex-col justify-center gap-2 border-b border-border pr-3 pl-9.5">
          <span className={cn("h-2 rounded-sm bg-surface-raised", BAR_WIDTHS[index % BAR_WIDTHS.length])} />
          <span className={cn("h-2 rounded-sm bg-surface-raised", BAR_WIDTHS[(index + 3) % BAR_WIDTHS.length])} />
        </li>
      ))}
    </ul>
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
