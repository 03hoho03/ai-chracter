import { Clover } from "lucide-react";

import { cn } from "@ai-character-chat/ui/lib/utils";

/** 잔량 한 줄.
 *
 * 형태는 `ContentCard`의 조회수 묶음(`ContentCardMetric`)을 그대로 쓴다: 아이콘 + 숫자,
 * `sr-only`에 전체 문장 / `aria-hidden`에 축약 숫자. 새 표시 어휘를 만들지 않는 이유는
 * DESIGN.md §Components가 요구하는 "같은 표면 어휘"이기도 하고, 조회수가 이미 **무채색 숫자**의
 * 이 앱 표준이기 때문이다.
 *
 * 🔴 **초록을 쓰지 않는다.** 이름이 초록을 부르지만 DESIGN.md §Colors One-Accent Rule이 새 UI 색
 * 발명을 금지한다 — 이 시스템의 유채색은 `primary`/`ring`·`destructive`·사용자 콘텐츠 셋뿐이다.
 *
 * 🔴 **부족 상태는 `text-primary` 잉크이지 솔리드 채움이 아니다.** 밝기 예산 규칙이 "화면당
 * 하나"로 관리하는 것은 솔리드 채움이고(채팅=전송 버튼, 이미지=생성 버튼), 잉크는 그 예산을
 * 쓰지 않는다. `text-primary`의 대비 대역은 5.78~7.18:1로 DESIGN.md §Colors에 실측돼 있다.
 *
 * 🔴 **부족은 색으로만 말하지 않는다**(WCAG 1.4.1). `text-primary`만으로 갈랐을 때
 * 색각 이상이나 저대비 환경에서는 충분/부족이 **같은 숫자 한 줄**로 보였다 — 스크린리더는
 * `sr-only` 문장으로 이미 구분했지만 그건 눈으로 보는 쪽을 구제하지 않는다. 그래서 그 문장이
 * 쓰던 말을 화면에도 꺼낸다. 어휘는 DESIGN.md §Status badges가 정한 그대로다 — **상태는
 * 글자와 잉크 명도로 가르고 색상(hue)으로 가르지 않는다**(같은 절: "중립 상태 안의 위계는
 * 잉크 명도로 만든다"). 가운뎃점 구분은 `TabsTrigger`의 `변형 · 준비 중`과 같은 관용구다.
 * 새 색·새 토큰·새 채움을 만들지 않았다.
 *
 * 정지 상태 그림자 없음(§Elevation Flat-at-Rest), 채움 없음(§Status badges — `bg-muted`는 카드·팝오버
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
      <span aria-hidden>
        {balance.toLocaleString()}
        {isInsufficient ? " · 부족해요" : ""}
      </span>
    </span>
  );
}
