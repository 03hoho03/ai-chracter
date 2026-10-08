import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { ChevronLeft, ListOrdered, Type } from "lucide-react";
import type { Ref } from "react";

type ViewerTopBarProps = {
  ref: Ref<HTMLElement>;
  id: string;
  novelId: string;
  episodeLabel: string;
  isVisible: boolean;
  isSettingsOpen: boolean;
  settingsPanelId: string;
  tocButtonRef: Ref<HTMLButtonElement>;
  settingsButtonRef: Ref<HTMLButtonElement>;
  onOpenToc: () => void;
  onToggleSettings: () => void;
};

/** 읽기 화면의 위 바 — 뒤로(작품 정보) · 화 제목 · 목차 · 보기 설정. 본문 위에 겹쳐 뜨는 일시적 표면이라 전역 헤더와
 * 같은 `h-14` 자리를 쓰되 그림자 없이 `border-b` 로만 본문과 갈린다. 숨은 동안은 `inert` 라 포커스·보조기기에서
 * 빠진다. 등장·퇴장은 장식 전환이라 `motion-safe:` 로만 움직인다.
 *
 * 화 제목은 `<p>` 다 — 이 페이지의 `h1` 은 본문 머리에 있다. */
export function ViewerTopBar({
  ref,
  id,
  novelId,
  episodeLabel,
  isVisible,
  isSettingsOpen,
  settingsPanelId,
  tocButtonRef,
  settingsButtonRef,
  onOpenToc,
  onToggleSettings,
}: ViewerTopBarProps) {
  return (
    <nav
      ref={ref}
      id={id}
      aria-label="읽기 메뉴"
      inert={!isVisible}
      className={cn(
        "fixed inset-x-0 top-0 z-30 border-b border-border bg-background px-safe pt-safe ease-out motion-safe:transition-[transform,opacity] motion-safe:duration-200",
        !isVisible && "-translate-y-full opacity-0",
      )}
    >
      <div className="flex h-14 items-center gap-1 px-4 sm:px-6">
        <Button asChild variant="ghost" size="icon" className="-ml-2 shrink-0">
          <Link to="/novels/$novelId" params={{ novelId }} aria-label="작품 정보">
            <ChevronLeft aria-hidden />
          </Link>
        </Button>
        <p className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">{episodeLabel}</p>
        <Button ref={tocButtonRef} type="button" variant="ghost" size="icon" aria-label="목차" className="shrink-0" onClick={onOpenToc}>
          <ListOrdered aria-hidden />
        </Button>
        <Button
          ref={settingsButtonRef}
          type="button"
          variant="ghost"
          size="icon"
          aria-label="보기 설정"
          aria-expanded={isSettingsOpen}
          aria-controls={isSettingsOpen ? settingsPanelId : undefined}
          className="-mr-2 shrink-0"
          onClick={onToggleSettings}
        >
          <Type aria-hidden />
        </Button>
      </div>
    </nav>
  );
}
