import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";

import { useSessionQuery } from "@/entities/session";
import { useLogoutMutation } from "@/features/logout";

import { ADMIN_NAV_ITEMS } from "../config/nav";

export function AdminSidebar() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const session = useSessionQuery();
  const navigate = useNavigate();
  const logoutMutation = useLogoutMutation();

  async function handleLogout() {
    await logoutMutation.mutateAsync();
    await navigate({ to: "/login" });
  }

  return (
    <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-border bg-card">
      <div className="px-4 py-4">
        <span className="text-base font-semibold tracking-tight text-foreground">또나 어드민</span>
      </div>

      <nav className="flex flex-1 flex-col gap-1 px-2">
        {ADMIN_NAV_ITEMS.map((item) => {
          const isActive = isNavItemActive(pathname, item.to);
          return (
            <Link
              key={item.to}
              to={item.to}
              className={cn(
                "rounded-lg border border-input px-3 py-2 text-sm font-medium text-foreground outline-none motion-safe:transition-colors hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
                isActive && "border-primary bg-primary/10 text-primary hover:bg-primary/15",
              )}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="flex flex-col gap-2 border-t border-border px-4 py-4">
        {session.data && <span className="truncate text-xs text-muted-foreground">{session.data.email}</span>}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void handleLogout()}
          disabled={logoutMutation.isPending}
        >
          로그아웃
        </Button>
      </div>
    </aside>
  );
}

/** "/"는 모든 경로의 접두사라 홈만 정확히 일치할 때 활성으로 본다.
 * 나머지는 하위 라우트(`/reports/$reportId` 등)도 같은 항목으로 활성 표시한다. */
function isNavItemActive(pathname: string, to: string) {
  if (to === "/") return pathname === "/";
  return pathname === to || pathname.startsWith(`${to}/`);
}
