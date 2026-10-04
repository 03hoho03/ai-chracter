import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

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
export function AdminSidebar() {
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
        {/* 이름이 지금 할 동작을 말한다. `aria-expanded` 를 달지 않는 이유: 내비는 접혀도 아이콘으로 늘 보여 "숨김"이
            아니고, `aria-expanded` + `aria-controls` 짝을 달면 나중에 내비 안에서 확인 모달을 열 때 포커스 복원
            래퍼가 이 버튼을 "연 자리" 후보로 잡는다. */}
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

      <AdminNavList isCollapsed={isCollapsed} />
      <AdminAccountFooter isCollapsed={isCollapsed} />
    </aside>
  );
}
