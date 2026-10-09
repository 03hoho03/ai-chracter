import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";

import { formatIdentityRequiredMessage, type IdentityRequiredReason } from "../model/identityRequiredMessage";

type IdentityRequiredNoticeProps = {
  reason: IdentityRequiredReason;
  /** `GET /me` 의 `dailyFreeChatTurns`. 세션을 아직 못 읽었으면 비워 둔다(숫자 없이 말한다). */
  dailyFreeChatTurns?: number;
  className?: string;
};

/** 본인인증을 하지 않아 막힌 자리의 안내. 잘못한 것이 없으므로 경고 틴트(`destructive`)도 `role="alert"`도 쓰지 않는다 —
 * 채팅의 "클로버를 쓰지 않았어요"·"앞 턴이 진행 중" 배너와 같은 중립 표면(보더 한 줄)에 사실과 다음 행동만 둔다.
 *
 * 인증하는 곳은 마이페이지 하나라 링크도 하나다. 링크가 outline 인 것은 이 안내가 놓이는 화면에 이미 그 화면의
 * 솔리드 채움(출석체크·전송)이 있기 때문이다. */
export function IdentityRequiredNotice({ reason, dailyFreeChatTurns, className }: IdentityRequiredNoticeProps) {
  return (
    <div
      role="status"
      className={cn(
        "flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-lg border border-border px-3.5 py-2.5",
        className,
      )}
    >
      <p className="min-w-0 flex-1 basis-48 text-xs break-keep text-muted-foreground">
        {formatIdentityRequiredMessage(reason, dailyFreeChatTurns)}
      </p>
      <Button asChild variant="outline" size="sm">
        <Link to="/mypage">본인인증하기</Link>
      </Button>
    </div>
  );
}
