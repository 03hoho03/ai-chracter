import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { Sparkles } from "lucide-react";

import { useSessionQuery } from "../../../entities/session";
import { ContentTypeToggle } from "./ContentTypeToggle";
import { NotificationBell } from "./NotificationBell";
import { ProfileMenu } from "./ProfileMenu";
import { SearchInlineExpand } from "./SearchInlineExpand";

/**
 * techspec-global-nav-profile.md §1 — 로고 · 캐릭터/스토리 토글 · 검색 · 알림 벨 · 프로필로 고정 구성되며
 * 모든 화면에서 동일하게 노출된다(`routes/__root.tsx`에 마운트). 크롬은 항상 얇게 유지한다(DESIGN.md §1).
 */
export function Header() {
  const { data: me } = useSessionQuery();

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-2 px-4 sm:px-6">
        <Link
          to="/"
          className="flex shrink-0 items-center gap-1.5 rounded-md focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <Sparkles aria-hidden className="size-5 text-primary" />
          <span className="hidden text-lg font-semibold tracking-tight text-foreground sm:inline">
            AI 캐릭터 챗
          </span>
        </Link>

        <ContentTypeToggle />

        <div className="ml-auto flex items-center gap-1">
          <SearchInlineExpand />
          {me ? (
            <>
              <NotificationBell />
              <ProfileMenu me={me} />
            </>
          ) : (
            <Button asChild size="sm">
              <Link to="/login">로그인</Link>
            </Button>
          )}
        </div>
      </div>
    </header>
  );
}
