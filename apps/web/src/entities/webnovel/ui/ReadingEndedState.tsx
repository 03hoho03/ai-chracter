import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { BookX } from "lucide-react";
import type { ComponentProps } from "react";

import { toReadingEndedNotice, type ReadingEndedAction } from "../model/readingEndedNotice";
import type { WebnovelEndedReason } from "../model/webnovelError";

/** 소장한 사람이 더는 읽을 수 없는 소설·화를 열었을 때의 안내 — 아이콘 원, 이유별 제목·본문, 다음 길. 그 상태가
 * 화면의 전부라 제목은 `h1` 이다. 아이콘 원은 색 없는 `secondary` 다(열람 종료는 위험이 아니라 상태다). 다음 길은
 * 첫 버튼만 솔리드 — 화면당 솔리드 채움 하나. */
export function ReadingEndedState({
  reason,
  refundedAmount,
}: {
  reason: WebnovelEndedReason | undefined;
  refundedAmount: number;
}) {
  const notice = toReadingEndedNotice(reason, refundedAmount);

  return (
    <div className="flex flex-col items-center gap-3 px-6 py-16 text-center break-keep">
      <span className="flex size-14 items-center justify-center rounded-full bg-secondary">
        <BookX aria-hidden className="size-6 text-muted-foreground" />
      </span>
      <h1 className="text-lg font-semibold text-foreground">{notice.title}</h1>
      <p className="max-w-sm text-sm text-pretty text-muted-foreground">{notice.body}</p>
      <div className="mt-3 flex flex-wrap justify-center gap-2">
        {notice.actions.map((action, index) => (
          <Button key={action} asChild variant={index === 0 ? "default" : "outline"}>
            <EndedActionLink action={action} />
          </Button>
        ))}
      </div>
    </div>
  );
}

/** 받은 나머지 속성은 그대로 넘긴다 — `Button asChild` 의 직계 자식이라 Radix 가 얹는 속성이 사라지지 않게. */
function EndedActionLink({
  action,
  ...props
}: { action: ReadingEndedAction } & Omit<ComponentProps<typeof Link>, "to" | "params" | "search" | "hash" | "children">) {
  switch (action) {
    case "cloverHistory":
      return (
        <Link to="/clover/history" {...props}>
          클로버 내역
        </Link>
      );
    case "browse":
      return (
        <Link to="/webnovels" {...props}>
          노벨 둘러보기
        </Link>
      );
    case "home":
      return (
        <Link to="/" {...props}>
          홈으로
        </Link>
      );
  }
}
