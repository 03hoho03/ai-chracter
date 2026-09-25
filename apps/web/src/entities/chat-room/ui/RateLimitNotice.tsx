import { useEffect, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { RotateCw } from "lucide-react";

import { formatChatRateLimitAnnouncement, formatChatRateLimitMessage, type ChatRateLimit } from "../model/chatRateLimit";

type RateLimitNoticeProps = {
  rateLimit: ChatRateLimit;
  /** 문구만 갈린다 — 미리보기는 "채팅과 같은 한도"라는 사실을 먼저 말한다. */
  surface: "chat" | "preview";
  /** 미리보기 배너에는 재시도가 없다 — 넘기지 않으면 버튼이 그려지지 않는다. */
  onRetry?: () => void;
};

/**
 * 유저별 상한(429 USER_LIMIT)에 걸렸을 때의 배너. 껍데기는
 * 실제 채팅·미리보기의 기존 오류 배너를 그대로 쓰고(정지 상태 그림자 없음 · destructive 틴트)
 * 안의 문구와 버튼만 창(minute/day)에 따라 갈린다.
 *
 * 카운트다운은 `features/sign-up`의 `EmailVerifyStep`과 같은 모양이다(1초 setInterval + 0에서 정지).
 * **day 창에는 걸지 않는다** — `retryAfterSeconds`가 최대 86400이라 초 타이머는 "자정에 열린다"는
 * 사실을 숫자로 바꿔 놓기만 하고, 그 사이 탭을 떠나면 값이 어긋난다.
 */
export function RateLimitNotice({ rateLimit, surface, onRetry }: RateLimitNoticeProps) {
  const [secondsLeft, setSecondsLeft] = useState(rateLimit.retryAfterSeconds);

  // rateLimit은 실패할 때마다 새로 만들어지는 객체라, 같은 초가 두 번 와도 이 effect가 다시 돈다
  // (값으로 비교하면 "30초 뒤 또 30초"에서 타이머가 이어져 0에 멈춘 채로 남는다).
  useEffect(() => {
    if (rateLimit.window !== "minute") return;
    setSecondsLeft(rateLimit.retryAfterSeconds);
    const timer = setInterval(() => {
      setSecondsLeft((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [rateLimit]);

  const isWaiting = rateLimit.window === "minute" && secondsLeft > 0;

  // 대기 중 비활성은 `disabled`가 아니라 `aria-disabled`다 — `disabled`면 카운트다운이 끝나기
  // 전까지 버튼이 탭 순회에서 통째로 빠져 "왜 못 누르는지"가 키보드 사용자에게 닿지 않는다
  // (apps/web/CLAUDE.md §포커스). pointer-events-none이 포인터만 막으므로 핸들러에 early return을 둔다.
  function handleRetry() {
    if (isWaiting) return;
    onRetry?.();
  }

  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-3.5 py-2.5">
      <span aria-hidden className="min-w-0 break-keep text-xs text-destructive-text">
        {formatChatRateLimitMessage(rateLimit, surface, secondsLeft)}
      </span>
      {/* role="alert" sr-only 쌍둥이. 보이는 문구는 매초 바뀌어 aria-hidden으로 숨기고,
          이 문구는 formatChatRateLimitAnnouncement가 담당한다 — secondsLeft를 받지 않아 마운트
          1회 말고는 값이 바뀔 길이 없다(뮤테이션이 원리적으로 불가능해 alert가 초마다 재발화하지
          않는다). */}
      <span role="alert" className="sr-only">
        {formatChatRateLimitAnnouncement(rateLimit, surface)}
      </span>
      {/* day 창에는 재시도를 두지 않는다 — 자정까지 눌러도 같은 429가 돌아온다. */}
      {!!onRetry && rateLimit.window === "minute" && (
        <Button
          variant="destructive"
          size="sm"
          aria-disabled={isWaiting}
          className="shrink-0 aria-disabled:pointer-events-none aria-disabled:opacity-65"
          onClick={handleRetry}
        >
          <RotateCw aria-hidden className="size-3.5" />
          다시 시도
        </Button>
      )}
    </div>
  );
}
