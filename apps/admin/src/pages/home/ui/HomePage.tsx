import { Button } from "@ai-character-chat/ui/components/button";
import { useNavigate } from "@tanstack/react-router";

import { useSessionQuery } from "../../../entities/session";
import { useLogoutMutation } from "../../../features/logout";

export function HomePage() {
  const session = useSessionQuery();
  const navigate = useNavigate();
  const logoutMutation = useLogoutMutation();

  async function handleLogout() {
    await logoutMutation.mutateAsync();
    await navigate({ to: "/login" });
  }

  return (
    <main className="flex min-h-screen flex-col gap-4 p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-foreground">AI 캐릭터 챗 관리자</h1>
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          {session.data && <span>{session.data.email}</span>}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleLogout}
            disabled={logoutMutation.isPending}
          >
            로그아웃
          </Button>
        </div>
      </div>
    </main>
  );
}
