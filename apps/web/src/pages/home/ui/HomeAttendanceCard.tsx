import { Link } from "@tanstack/react-router";
import { CalendarCheck, ChevronRight } from "lucide-react";

/** 홈의 출석판 진입 카드 — 한 줄 링크 행. 본문 흐름 안의 카드라 상시 띠가 아니다.
 *
 * 점은 이 카드의 유일한 강조라 primary 다. 알림 배지는 "새 것이 있다" 는 수량 표시라 무채로 물러나지만, 이 점은 "오늘 할
 * 수 있는 행동이 있다" 는 강조 지점이다. 보조 문장이 같은 사실을 글로 말하므로 점은 낭독에서 숨긴다. */
export function HomeAttendanceCard({ detail, showDot }: { detail: string | null; showDot: boolean }) {
  return (
    <Link
      to="/attendance"
      className="flex items-center gap-3 rounded-xl bg-card px-4 py-3 motion-safe:transition-colors hover:bg-secondary focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      <CalendarCheck aria-hidden className="size-5 shrink-0 text-muted-foreground" />
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="text-sm font-semibold text-foreground">또 만나, 28일</span>
        {detail !== null && <span className="text-xs break-keep text-muted-foreground">{detail}</span>}
      </span>
      {showDot && <span aria-hidden className="size-2 shrink-0 rounded-full bg-primary" />}
      <ChevronRight aria-hidden className="size-4 shrink-0 text-muted-foreground" />
    </Link>
  );
}
