import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { ImagePlus, Sparkles } from "lucide-react";

import { useSessionQuery } from "../../../entities/session";
import { ContentTypeToggle } from "./ContentTypeToggle";
import { NotificationBell } from "./NotificationBell";
import { ProfileMenu } from "./ProfileMenu";
import { SearchInlineExpand } from "./SearchInlineExpand";

/**
 * techspec-global-nav-profile.md §1 — 로고 · 캐릭터/스토리 토글 · 이미지 생성 · 검색 · 알림 벨 · 프로필로 고정 구성되며
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

        {/* min-w-0 — 아이콘 버튼은 모두 shrink-0이라, 폭이 모자랄 때 줄어들 수 있는 건 펼친 검색뿐이다.
            이 그룹이 기본값 min-width:auto면 그 축소가 막혀 헤더가 뷰포트를 넘는다(390px에서 실측). */}
        <div className="ml-auto flex min-w-0 items-center gap-1">
          {/* /studio/images의 유일한 진입점이 빌더 이미지 피커의 새 탭 링크뿐이었다. 헤더에 상시 노출하되
              로그인 분기는 두지 않는다 — 비로그인 클릭은 라우트의 requireSession이 /login?redirect=로 처리한다.
              아이콘은 로고의 Sparkles와 겹치지 않게 ImagePlus("이미지를 새로 만든다")를 쓴다. */}
          <Button asChild variant="ghost" size="icon" aria-label="이미지 생성">
            <Link to="/studio/images">
              <ImagePlus aria-hidden />
            </Link>
          </Button>
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
