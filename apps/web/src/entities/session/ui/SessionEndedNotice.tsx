import { Button } from "@ai-character-chat/ui/components/button";
import { Link, useRouterState } from "@tanstack/react-router";

import { loginRedirectTarget } from "../lib/loginRedirectTarget";
import type { SessionEndReason } from "../model/sessionEndReason";
import { SUSPENDED_ERROR_MESSAGE } from "../model/suspendedAccount";

const NOTICE_CLASS =
  "flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-lg border border-border px-3.5 py-2.5";
const MESSAGE_CLASS = "min-w-0 flex-1 basis-48 text-xs break-keep text-muted-foreground";

/** 세션이 끝나 보내지 못한 자리(채팅·빌더 미리보기)의 안내. 응답 생성이 실패한 것이 아니고 다시 보내도 같은 거절이라
 * 재시도 버튼도, 경고 틴트(`destructive`)·`role="alert"` 도 쓰지 않는다 — 본인인증 안내(`IdentityRequiredNotice`)와 같은
 * 중립 표면에 사실과 다음 행동만 둔다.
 *
 * 로그인이 풀렸으면 로그인 화면으로 보내고, 로그인 뒤 지금 주소로 돌아오게 한다. 새 메시지든 다시 생성하기든 미리보기 시작이든
 * 서버가 거절해 아무것도 처리되지 않았으므로, 어느 경우에나 참인 "요청이 처리되지 않았다"로 말한다(화면에 남은 내
 * 메시지는 저장되지 않아 다시 들어오면 사라진다). 정지는 다시 로그인해도 풀리지 않아 링크 없이 문의처만 말한다. */
export function SessionEndedNotice({ reason }: { reason: SessionEndReason }) {
  const redirect = useRouterState({ select: (state) => loginRedirectTarget(state.location) });

  if (reason === "suspended") {
    return (
      <div role="status" className={NOTICE_CLASS}>
        <p className={MESSAGE_CLASS}>{SUSPENDED_ERROR_MESSAGE}</p>
      </div>
    );
  }

  return (
    <div role="status" className={NOTICE_CLASS}>
      <p className={MESSAGE_CLASS}>로그인이 풀려 요청이 처리되지 않았어요.</p>
      <Button asChild variant="outline" size="sm">
        <Link to="/login" search={{ redirect }}>
          다시 로그인
        </Link>
      </Button>
    </div>
  );
}
