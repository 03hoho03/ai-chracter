import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useNavigate, useRouter } from "@tanstack/react-router";
import { LogOut } from "lucide-react";
import { useRef } from "react";

import { useSessionQuery } from "@/entities/session";
import { useLogoutMutation } from "@/features/logout";

/** 사이드바·드로어 아래의 세션 이메일 + 로그아웃. ghost 버튼의 기본 hover(`muted`)는 `card`·`popover` 위에서 사라져 `secondary` 로 덮는다. */
export function AdminAccountFooter({ isCollapsed = false }: { isCollapsed?: boolean }) {
  const session = useSessionQuery();
  const navigate = useNavigate();
  const router = useRouter();
  const logoutMutation = useLogoutMutation();
  const logoutAttemptRef = useRef(0);

  // 이동을 먼저 하고 로그아웃은 그 뒤에 한다. 편집 화면에 저장하지 않은 변경이 있으면 이동이 이탈 확인에 걸리는데,
  // 세션을 먼저 끊으면 "계속 편집"을 골라도 세션 없는 화면에 남아 저장이 실패한다. 확인에서 머물면 이 이동의 약속은
  // 풀리지 않다가 다음 이동이 끝날 때 함께 풀리므로, 그때 이것이 마지막 로그아웃 시도이고 실제로 로그인 화면에
  // 와 있을 때만 로그아웃한다.
  async function handleLogout() {
    const attempt = ++logoutAttemptRef.current;
    await navigate({ to: "/login" });
    if (attempt !== logoutAttemptRef.current || router.state.location.pathname !== "/login") return;
    await logoutMutation.mutateAsync();
  }

  return (
    <div className={cn("flex shrink-0 flex-col gap-2 border-t border-border py-3", isCollapsed ? "items-center px-2" : "px-3")}>
      {isCollapsed ? (
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="로그아웃"
          title="로그아웃"
          className="hover:bg-secondary"
          onClick={() => void handleLogout()}
          disabled={logoutMutation.isPending}
        >
          <LogOut aria-hidden />
        </Button>
      ) : (
        <>
          {session.data && <span className="truncate px-3 text-xs text-muted-foreground">{session.data.email}</span>}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="w-full justify-start px-3 hover:bg-secondary"
            onClick={() => void handleLogout()}
            disabled={logoutMutation.isPending}
          >
            <LogOut aria-hidden />
            로그아웃
          </Button>
        </>
      )}
    </div>
  );
}
