import { cn } from "@ai-character-chat/ui/lib/utils";
import { Check, Gift } from "lucide-react";

import type { AttendanceCell } from "@/entities/clover";

import { attendanceCellLook, cellStatusLabel, formatCellAmount } from "../model/attendanceCellLook";
import { formatCloverAmount } from "../model/attendanceCopy";

const CELL_STATUS_SPOKEN: Record<AttendanceCell["status"], string> = {
  claimed: "받음",
  today: "오늘 받을 수 있음",
  upcoming: "예정",
};

/** 28칸 판. 칸은 누를 수 없다 — 이 화면에서 누르는 것은 수령 버튼 하나다.
 *
 * 320px 폭에서 7열 칸은 바깥 약 37.7px, 가장 좁은 오늘 칸(테두리 2px)의 안쪽이 약 33.7px 다. 그래서 `sm` 미만은 번호만
 * (판 위 한 줄이 번호의 뜻을 말한다), 금액은 쉼표 없이, 받음 칸은 체크 아이콘만 둔다. 칸 높이는 테두리 두께와 무관하게
 * `h-16` 으로 고정해 오늘 → 받음으로 바뀌어도 칸 크기가 같다. `sm` 이상은 정사각 칸에 "N일차"·쉼표·"받음" 을 쓴다.
 *
 * 보이는 글자는 낭독에서 숨기고 칸마다 문장 하나("7일차, 1,600클로버, 오늘 받을 수 있음")를 읽힌다 — 좁은 칸의 줄인
 * 표기가 낭독에 닿지 않는다. */
export function AttendanceBoard({
  cells,
  justClaimedSeq,
}: {
  cells: readonly AttendanceCell[];
  /** 방금 받은 칸. 그 칸의 체크만 짧게 나타난다(상태가 바뀐 자리를 짚는 것이지 축하 연출이 아니다). */
  justClaimedSeq: number | null;
}) {
  const claimedCount = cells.filter((cell) => cell.status === "claimed").length;

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs break-keep text-muted-foreground">칸 번호는 출석한 횟수예요.</p>
      <ol aria-label={`출석판, ${cells.length}칸 중 ${claimedCount}칸 받음`} className="grid grid-cols-7 gap-1 sm:gap-2">
        {cells.map((cell) => (
          <AttendanceCellItem key={cell.seq} cell={cell} isJustClaimed={cell.seq === justClaimedSeq} />
        ))}
      </ol>
    </div>
  );
}

function AttendanceCellItem({ cell, isJustClaimed }: { cell: AttendanceCell; isJustClaimed: boolean }) {
  const look = attendanceCellLook(cell);
  const compactLabel = cellStatusLabel(cell.status, true);
  const wideLabel = cellStatusLabel(cell.status, false);
  const spoken = [`${cell.seq}일차`, `${formatCloverAmount(cell.amount)}클로버`, look.showGift && "특별 보상", CELL_STATUS_SPOKEN[cell.status]]
    .filter(Boolean)
    .join(", ");

  return (
    <li
      className={cn(
        "box-border flex h-16 min-w-0 flex-col items-center justify-center rounded-lg py-1 text-center sm:aspect-square sm:h-auto",
        look.cellClassName,
      )}
    >
      <span className="sr-only">{spoken}</span>
      <span aria-hidden className="flex min-w-0 flex-col items-center">
        <span
          className={cn(
            "flex items-center gap-0.5 text-xs font-medium tabular-nums",
            cell.status === "claimed" ? "text-muted-foreground" : "text-foreground",
          )}
        >
          {cell.seq}
          <span className="hidden sm:inline">일차</span>
          {look.showGift && <Gift className="size-3 shrink-0" />}
        </span>
        <span className={cn("text-badge leading-4 tabular-nums", look.amountClassName)}>
          <span className="sm:hidden">{formatCellAmount(cell.amount, true)}</span>
          <span className="hidden sm:inline">{formatCellAmount(cell.amount, false)}</span>
        </span>
        <span className={cn("flex items-center gap-0.5 text-badge leading-4", look.statusClassName)}>
          {compactLabel !== null && <span className="sm:hidden">{compactLabel}</span>}
          {wideLabel !== null && <span className="hidden sm:inline">{wideLabel}</span>}
          {cell.status === "claimed" && (
            <Check
              className={cn(
                "size-3 shrink-0",
                isJustClaimed && "motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-95 motion-safe:duration-200",
              )}
            />
          )}
        </span>
      </span>
    </li>
  );
}

/** 판을 기다리는 동안의 자리. 진행 표시라 움직임을 동작 줄이기 설정으로 멈추지 않는다 — 멈추면 멈춘 화면으로 읽힌다. */
export function AttendanceBoardSkeleton() {
  return (
    <div className="flex flex-col gap-2" aria-hidden>
      <div className="h-5 w-40 animate-pulse rounded bg-secondary" />
      <div className="grid grid-cols-7 gap-1 sm:gap-2">
        {Array.from({ length: 28 }, (_, index) => (
          <div key={index} className="h-16 animate-pulse rounded-lg bg-card sm:aspect-square sm:h-auto" />
        ))}
      </div>
    </div>
  );
}
