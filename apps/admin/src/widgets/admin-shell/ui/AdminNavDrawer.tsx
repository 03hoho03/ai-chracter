import { Button } from "@ai-character-chat/ui/components/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@ai-character-chat/ui/components/sheet";
import { Menu } from "lucide-react";
import { useRef, useState } from "react";

import { MAIN_CONTENT_ID } from "@/shared/config/landmarks";
import { useIsDesktopLayout } from "@/shared/lib/useMediaQuery";

import { AdminAccountFooter } from "./AdminAccountFooter";
import { AdminNavList } from "./AdminNavList";

/**
 * `lg` 미만 상단바의 버거 + 좌측 드로어. 트리거와 열림 상태를 이 컴포넌트가 소유한다(상단바는 이것 하나만 둔다).
 * 포커스 트랩·Esc·스크롤 잠금은 Sheet(Radix Dialog) 기본 동작이다.
 */
export function AdminNavDrawer() {
  const [isOpen, setIsOpen] = useState(false);
  const isDesktop = useIsDesktopLayout();
  const isClosingForNavigationRef = useRef(false);
  const contentRef = useRef<HTMLDivElement>(null);

  // 드로어를 연 채 창을 `lg` 이상으로 넓히면 버거가 숨어 닫을 길이 스크림뿐이다 — 넓어지는 순간 닫는다.
  // 렌더 중 자기 상태를 고치는 것이라 효과 없이 한 번 더 렌더될 뿐이다.
  if (isDesktop && isOpen) setIsOpen(false);

  function handleNavigate() {
    isClosingForNavigationRef.current = true;
    setIsOpen(false);
  }

  return (
    <Sheet open={isOpen} onOpenChange={setIsOpen}>
      <SheetTrigger asChild>
        <Button type="button" variant="ghost" size="icon" aria-label="메뉴 열기">
          <Menu aria-hidden />
        </Button>
      </SheetTrigger>
      <SheetContent
        ref={contentRef}
        side="left"
        aria-describedby={undefined}
        className="gap-0"
        onOpenAutoFocus={(event) => {
          // Radix 는 열릴 때 링크를 건너뛰고 첫 버튼에 포커스를 줘서 그대로 두면 로그아웃에 앉는다(Enter 한 번이면
          // 로그아웃된다). 지금 화면 항목, 없으면 첫 항목에서 시작한다.
          const content = contentRef.current;
          const link = content?.querySelector<HTMLElement>('a[aria-current="page"]') ?? content?.querySelector<HTMLElement>("a");
          if (!link) return;
          event.preventDefault();
          link.focus();
        }}
        onCloseAutoFocus={(event) => {
          // Esc·스크림·닫기 X 는 Radix 기본대로 버거로 돌아간다. 항목을 눌러 닫혔으면 새 화면 본문에서 읽기가
          // 시작되도록 본문으로 보낸다(버거로 돌아가면 다음 Tab 이 다시 상단바부터다).
          if (!isClosingForNavigationRef.current) return;
          isClosingForNavigationRef.current = false;
          event.preventDefault();
          // 이동이 편집 화면의 이탈 확인으로 막혔으면 그 확인 창이 먼저 포커스를 가져갔다 — 빼앗지 않는다.
          const active = document.activeElement;
          const isHeldElsewhere =
            active !== null && active !== document.body && active.isConnected && !contentRef.current?.contains(active);
          if (isHeldElsewhere) return;
          document.getElementById(MAIN_CONTENT_ID)?.focus();
        }}
      >
        <SheetHeader className="px-6">
          <SheetTitle className="text-sm font-semibold">또나 어드민</SheetTitle>
        </SheetHeader>
        <AdminNavList onNavigate={handleNavigate} />
        <AdminAccountFooter />
      </SheetContent>
    </Sheet>
  );
}
