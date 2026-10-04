import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { PanelLeftClose, PanelLeftOpen, Search } from "lucide-react";

import { Kbd } from "@/shared/ui/Command";

import { IS_APPLE_PLATFORM } from "../model/useAdminShortcuts";
import { useSidebarCollapsed } from "../model/useSidebarCollapsed";
import { AdminAccountFooter } from "./AdminAccountFooter";
import { AdminNavList } from "./AdminNavList";

/**
 * `lg` 이상의 좌측 사이드바. 펼침 224px(바뀌기 전 사이드바와 같은 폭이라 본문 위치가 그대로다) / 접힘 64px 아이콘 레일.
 * `lg` 미만에서는 `display:none` 이고 같은 내비 목록을 상단바의 드로어가 그린다.
 *
 * 높이는 `h-dvh`(모바일 주소창이 접혀도 바닥이 맞는다)이고 내비만 스크롤한다 — 1024×768 같은 낮은 화면에서도
 * 아래 세션·로그아웃이 밀려나지 않는다. `overflow-hidden` 은 aside 자신에만 걸어(접기 전이 중 글자 잘림용)
 * 자기 sticky 에 영향이 없다. 조상에는 overflow 를 걸지 않는다 — 걸면 sticky 가 죽는다.
 */
type AdminSidebarProps = {
  onOpenPalette: () => void;
};

export function AdminSidebar({ onOpenPalette }: AdminSidebarProps) {
  const { isCollapsed, toggle } = useSidebarCollapsed();

  return (
    <aside
      className={cn(
        "sticky top-0 hidden h-dvh shrink-0 flex-col overflow-hidden border-r border-border bg-card motion-safe:transition-[width] motion-safe:duration-200 motion-safe:ease-out lg:flex",
        isCollapsed ? "w-16" : "w-56",
      )}
    >
      <div className={cn("flex h-14 shrink-0 items-center", isCollapsed ? "justify-center" : "justify-between pr-2 pl-6")}>
        {!isCollapsed && <span className="truncate text-sm font-semibold text-foreground">또나 어드민</span>}
        {/* 이름이 지금 할 동작을 말한다. `aria-expanded` 를 달지 않는 이유: 접힌 레일에서도 각 항목의 라벨이 `sr-only`
            로 접근성 트리에 그대로 남아, 스크린리더 사용자에게는 펼쳐지거나 접히는 것이 없다 — 알릴 상태 변화가 없다.
            `aria-pressed` 도 달지 않는다. 이름이 동작에 따라 바뀌는 버튼에 눌림 상태를 더하면 상태가 둘로 읽힌다. */}
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={isCollapsed ? "사이드바 펼치기" : "사이드바 접기"}
          title={isCollapsed ? "사이드바 펼치기" : "사이드바 접기"}
          className="hover:bg-secondary"
          onClick={toggle}
        >
          {isCollapsed ? <PanelLeftOpen aria-hidden /> : <PanelLeftClose aria-hidden />}
        </Button>
      </div>

      {/* 빠른 이동(팔레트)을 여는 자리. 단축키를 모르는 사람도 찾을 수 있게 늘 보인다. outline 의 hover 채움 `muted` 는
          사이드바 `card` 와 같은 값이라 `secondary` 로 덮는다. */}
      <div className={cn("shrink-0 pb-1", isCollapsed ? "flex justify-center px-2" : "px-3")}>
        <Button
          type="button"
          variant="outline"
          size={isCollapsed ? "icon" : "sm"}
          aria-haspopup="dialog"
          aria-keyshortcuts="Meta+K Control+K"
          aria-label={isCollapsed ? "빠른 이동" : undefined}
          title={isCollapsed ? "빠른 이동" : undefined}
          className={cn("hover:bg-secondary", !isCollapsed && "w-full justify-start")}
          onClick={onOpenPalette}
        >
          <Search aria-hidden className="text-muted-foreground" />
          {!isCollapsed && (
            <>
              빠른 이동
              <Kbd aria-hidden className="ml-auto">
                {IS_APPLE_PLATFORM ? "⌘K" : "Ctrl K"}
              </Kbd>
            </>
          )}
        </Button>
      </div>

      <AdminNavList isCollapsed={isCollapsed} />
      <AdminAccountFooter isCollapsed={isCollapsed} />
    </aside>
  );
}
