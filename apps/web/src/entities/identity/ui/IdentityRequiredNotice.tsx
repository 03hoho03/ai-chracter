import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";

/** 왜 본인인증이 필요한지는 자리마다 다르다. 무료 대화·출석·미션은 인증하면 **받는 것**이 생기고, 구매는 인증해야
 * **할 수 있는 것**이다 — 구매 자리에 "무료 대화를 받는다"를 쓰면 게이트가 꺼진 동안 거짓이 된다. */
export type IdentityRequiredReason = "free-rewards" | "purchase";

const MESSAGES: Record<IdentityRequiredReason, string> = {
  "free-rewards": "본인인증을 하면 매일 무료 대화 30턴과 출석·미션 클로버를 받을 수 있어요.",
  purchase: "클로버를 구매하려면 본인인증이 필요해요. 만 19세 이상만 구매할 수 있어요.",
};

type IdentityRequiredNoticeProps = {
  reason: IdentityRequiredReason;
  className?: string;
};

/** 본인인증을 하지 않아 막힌 자리의 안내. 잘못한 것이 없으므로 경고 틴트(`destructive`)도 `role="alert"`도 쓰지 않는다 —
 * 채팅의 "클로버를 쓰지 않았어요"·"앞 턴이 진행 중" 배너와 같은 중립 표면(보더 한 줄)에 사실과 다음 행동만 둔다.
 *
 * 인증하는 곳은 마이페이지 하나라 링크도 하나다. 링크가 outline 인 것은 이 안내가 놓이는 화면에 이미 그 화면의
 * 솔리드 채움(출석체크·전송)이 있기 때문이다. */
export function IdentityRequiredNotice({ reason, className }: IdentityRequiredNoticeProps) {
  return (
    <div
      role="status"
      className={cn(
        "flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-lg border border-border px-3.5 py-2.5",
        className,
      )}
    >
      <p className="min-w-0 flex-1 basis-48 text-xs break-keep text-muted-foreground">{MESSAGES[reason]}</p>
      <Button asChild variant="outline" size="sm">
        <Link to="/mypage">본인인증하기</Link>
      </Button>
    </div>
  );
}
