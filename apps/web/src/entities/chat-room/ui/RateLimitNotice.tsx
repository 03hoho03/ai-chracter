import { useEffect, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link, useRouterState } from "@tanstack/react-router";
import { RotateCw } from "lucide-react";

import {
  formatChatRateLimitAnnouncement,
  formatChatRateLimitMessage,
  getRateLimitLinks,
  type ChatRateLimit,
  type ChatRateLimitSurface,
} from "../model/chatRateLimit";

type RateLimitNoticeProps = {
  rateLimit: ChatRateLimit;
  /** 문구만 갈린다 — 미리보기는 "채팅과 같은 한도"라는 사실을 먼저 말하고, 상위 모델 방은 자정 약속을 하지 않는다. */
  surface: ChatRateLimitSurface;
  /** 미리보기 배너에는 재시도가 없다 — 넘기지 않으면 버튼이 그려지지 않는다. */
  onRetry?: () => void;
  /** 공개 가격 응답의 출석판 스위치(`attendance.enabled`). 못 받았으면 꺼진 것으로 넘긴다. 켜져 있으면 클로버 부족 문구가
   * 자정 대신 출석판을 말하고, 채팅 방에서는 "클로버 채우기" 옆에 출석판 버튼이 붙는다. */
  attendanceEnabled: boolean;
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
export function RateLimitNotice({ rateLimit, surface, onRetry, attendanceEnabled }: RateLimitNoticeProps) {
  const [secondsLeft, setSecondsLeft] = useState(rateLimit.retryAfterSeconds);
  // 충전하고 돌아올 곳. 충전 화면이 이 주소로 "돌아가기"를 두고, 결제창·로그인 왕복 뒤에도 잃지 않게 넘겨 다닌다. 거절된 메시지는
  // 채팅 방이 입력 초안에 남겨 두어, 돌아오면 입력창에 있다 — 그래서 이 배너에 다시 보내기를 두지 않는다(지금 누르면 같은
  // 거절이고, 충전 뒤에는 전송 버튼이 그 일을 한다).
  const returnTo = useRouterState({ select: (state) => state.location.href });

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
  const links = getRateLimitLinks(rateLimit, surface, attendanceEnabled);
  // 버튼이 둘이면 좁은 폭에서 문구가 몇 글자씩 쪼개지므로 버튼 묶음을 다음 줄로 내린다. 하나일 때는 지금 배치 그대로다.
  const hasManyLinks = links.length > 1;

  // 대기 중 비활성은 `disabled`가 아니라 `aria-disabled`다 — `disabled`면 카운트다운이 끝나기
  // 전까지 버튼이 탭 순회에서 통째로 빠져 "왜 못 누르는지"가 키보드 사용자에게 닿지 않는다
  // (apps/web/CLAUDE.md 포커스 절). pointer-events-none이 포인터만 막으므로 핸들러에 early return을 둔다.
  function handleRetry() {
    if (isWaiting) return;
    onRetry?.();
  }

  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 rounded-lg bg-destructive/10 px-3.5 py-2.5",
        hasManyLinks && "flex-wrap gap-y-2",
      )}
    >
      <span
        aria-hidden
        className={cn("min-w-0 break-keep text-xs text-destructive-text", hasManyLinks && "flex-1 basis-48")}
      >
        {formatChatRateLimitMessage(rateLimit, surface, secondsLeft, attendanceEnabled)}
      </span>
      {/* role="alert" sr-only 쌍둥이. 보이는 문구는 매초 바뀌어 aria-hidden으로 숨기고,
          이 문구는 formatChatRateLimitAnnouncement가 담당한다 — secondsLeft를 받지 않아 마운트
          1회 말고는 값이 바뀔 길이 없다(뮤테이션이 원리적으로 불가능해 alert가 초마다 재발화하지
          않는다). */}
      <span role="alert" className="sr-only">
        {formatChatRateLimitAnnouncement(rateLimit, surface, attendanceEnabled)}
      </span>
      {/* 클로버가 모자라면 채울 곳(구매·미션이 있는 허브)으로, 출석판이 켜져 있으면 출석판으로도 잇는다. 빌더
          미리보기에는 두지 않는다 — 누르면 만들던 화면을 떠난다(`getRateLimitLinks`). 버튼은 위 aria-hidden 문구 밖에
          둔다 — 그 안에 두면 접근성 트리에서 버튼이 사라진다. 출석판에는 돌아올 곳을 넘기지 않는다(출석판은 서치
          파라미터를 받지 않고, 받은 뒤 "대화 이어가기"가 최근 방으로 돌려보낸다). */}
      {links.length > 0 && (
        <div className="flex shrink-0 gap-2">
          {links.map((link) =>
            link === "clover" ? (
              <Button key={link} asChild variant="destructive" size="sm" className="shrink-0">
                <Link to="/clover" search={{ returnTo }}>
                  클로버 채우기
                </Link>
              </Button>
            ) : (
              <Button key={link} asChild variant="destructive" size="sm" className="shrink-0">
                <Link to="/attendance">출석판</Link>
              </Button>
            ),
          )}
        </div>
      )}
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
