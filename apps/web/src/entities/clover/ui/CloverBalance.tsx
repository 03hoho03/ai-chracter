import { Clover } from "lucide-react";

import { cn } from "@ai-character-chat/ui/lib/utils";

/** clover-techspec.md CT-16 (clover-goal-prompt.md CL-27) — 잔량 한 줄.
 *
 * 형태는 `ContentCard`의 조회수 묶음(`ContentCardMetric`)을 그대로 쓴다: 아이콘 + 숫자,
 * `sr-only`에 전체 문장 / `aria-hidden`에 축약 숫자. 새 표시 어휘를 만들지 않는 이유는
 * DESIGN.md §5가 요구하는 "같은 표면 어휘"이기도 하고, 조회수가 이미 **무채색 숫자**의
 * 이 앱 표준이기 때문이다.
 *
 * 🔴 **초록을 쓰지 않는다.** 이름이 초록을 부르지만 DESIGN.md §2 One-Accent Rule이 새 UI 색
 * 발명을 금지한다 — 이 시스템의 유채색은 `primary`/`ring`·`destructive`·사용자 콘텐츠 셋뿐이다.
 *
 * 🔴 **부족 상태는 `text-primary` 잉크이지 솔리드 채움이 아니다.** 밝기 예산 규칙이 "화면당
 * 하나"로 관리하는 것은 솔리드 채움이고(채팅=전송 버튼, 이미지=생성 버튼), 잉크는 그 예산을
 * 쓰지 않는다. `text-primary`의 대비 대역은 5.78~7.18:1로 DESIGN.md §2에 실측돼 있다.
 *
 * 정지 상태 그림자 없음(§4 Flat-at-Rest), 채움 없음(§5 Status badges — `bg-muted`는 카드·팝오버
 * 위에서 1.0000:1로 사라진다). 크기는 본문 기본보다 한 단 아래인 `text-xs`로, 조회수와 같다. */
export function CloverBalance({
  balance,
  isInsufficient = false,
  className,
}: {
  balance: number;
  isInsufficient?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 text-xs",
        isInsufficient ? "text-primary" : "text-muted-foreground",
        className,
      )}
    >
      <Clover aria-hidden className="size-3.5" />
      <span className="sr-only">
        클로버 {balance.toLocaleString()}개{isInsufficient ? " — 부족해요" : ""}
      </span>
      <span aria-hidden>{balance.toLocaleString()}</span>
    </span>
  );
}
