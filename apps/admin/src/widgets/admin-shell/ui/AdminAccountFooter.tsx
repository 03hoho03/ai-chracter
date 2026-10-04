import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useNavigate } from "@tanstack/react-router";
import { LogOut } from "lucide-react";

import { useSessionQuery } from "@/entities/session";
import { useLogoutMutation } from "@/features/logout";

/** 사이드바·드로어 아래의 세션 이메일 + 로그아웃. ghost 버튼의 기본 hover(`muted`)는 `card`·`popover` 위에서 사라져 `secondary` 로 덮는다. */
export function AdminAccountFooter({ isCollapsed = false }: { isCollapsed?: boolean }) {
  const session = useSessionQuery();
  const navigate = useNavigate();
  const logoutMutation = useLogoutMutation();

  async function handleLogout() {
    await logoutMutation.mutateAsync();
    await navigate({ to: "/login" });
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
