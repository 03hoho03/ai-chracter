import { Button } from "@ai-character-chat/ui/components/button";
import { useRouterState } from "@tanstack/react-router";
import { Search } from "lucide-react";

import { ADMIN_NAV_ITEMS } from "../config/nav";
import { resolveActiveNavTo } from "../lib/resolveActiveNavTo";
import { PALETTE_SHORTCUT } from "../model/useAdminShortcuts";
import { AdminNavDrawer } from "./AdminNavDrawer";

type AdminTopBarProps = {
  onOpenPalette: () => void;
};

/**
 * `lg` 미만의 상단바: 버거 · "또나 어드민" · 현재 화면명 · 빠른 이동(팔레트) 버튼. 높이 `h-14` 를 보더가 붙은 이 요소에 걸어 보더 포함
 * 56px 다. 화면명은 활성 내비 항목의 라벨이라 상세에서는 부모 목록 이름이 나오고, 좁으면 말줄임한다(화면 h1 이
 * 따로 있어 잘려도 정보가 사라지지 않는다).
 */
export function AdminTopBar({ onOpenPalette }: AdminTopBarProps) {
  const activeTo = useRouterState({ select: (state) => resolveActiveNavTo(state.location) });
  const screenName = ADMIN_NAV_ITEMS.find((item) => item.to === activeTo)?.label;

  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b border-border bg-background px-2 sm:px-4 lg:hidden">
      <AdminNavDrawer />
      <span className="shrink-0 text-sm font-semibold text-foreground">또나 어드민</span>
      {screenName && <span className="min-w-0 truncate text-sm text-muted-foreground">{screenName}</span>}
      {/* 손가락 포인터에서는 admin 전용 CSS 가 아이콘 버튼을 40px 로 올린다(버거와 같다). */}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label="빠른 이동"
        aria-haspopup="dialog"
        aria-keyshortcuts={PALETTE_SHORTCUT.ariaKeyShortcuts}
        className="ml-auto"
        onClick={onOpenPalette}
      >
        <Search aria-hidden />
      </Button>
    </header>
  );
}
