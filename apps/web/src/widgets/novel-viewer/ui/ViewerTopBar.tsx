import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronLeft, ListOrdered, Type } from "lucide-react";
import type { ReactNode, Ref } from "react";

import { VIEWER_BAR_ROW_PX } from "../lib/pageFit";
import type { ViewerRoute } from "../model/viewerSource";
import { NovelInfoLink } from "./ViewerLinks";

type ViewerTopBarProps = {
  ref: Ref<HTMLElement>;
  id: string;
  route: ViewerRoute;
  novelId: string;
  episodeLabel: string;
  /** 화 제목 밑 한 줄 — 화 번호와 화 안 위치("3/12화 · 3–4 / 16쪽", 스크롤 모드는 "3/12화 · 40%"). */
  location: string;
  isVisible: boolean;
  isSettingsOpen: boolean;
  settingsPanelId: string;
  tocButtonRef: Ref<HTMLButtonElement>;
  settingsButtonRef: Ref<HTMLButtonElement>;
  onOpenToc: () => void;
  onToggleSettings: () => void;
  /** 목차 앞에 더할 버튼(노벨의 댓글). */
  extraAction?: ReactNode;
};

/** 읽기 화면의 위 바 — 뒤로(작품 정보) · 화 제목과 그 밑 화 안 위치 · (노벨이면) 댓글 · 목차 · 보기 설정. 부를 때만 나타나는 일시적
 * 표면이라 전역 헤더와 같은 높이(56px 한 줄)를 쓰되 그림자 없이 `border-b` 로만 본문과 갈린다. 줄 높이는 판형 배율
 * 계산이 비워 두는 자리와 같은 상수라, 페이지 모드에서 바가 판형을 덮지 않는다. 숨은 동안은 `inert` 라 포커스·
 * 보조기기에서 빠진다. 등장·퇴장은 장식 전환이라 `motion-safe:` 로만 움직인다.
 *
 * 화 안 위치를 아래 바가 아니라 여기 두는 것은 페이지 모드 아래 바를 한 줄로 줄여 판형이 쓸 높이를 늘리려는 것이다
 * — 두 모드의 위 바가 같은 모양이 된다. 화 제목은 `<p>` 다 — 이 페이지의 `h1` 은 본문 머리에 있다. */
export function ViewerTopBar({
  ref,
  id,
  route,
  novelId,
  episodeLabel,
  location,
  isVisible,
  isSettingsOpen,
  settingsPanelId,
  tocButtonRef,
  settingsButtonRef,
  onOpenToc,
  onToggleSettings,
  extraAction,
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
      <div className="flex items-center gap-1 px-4 sm:px-6" style={{ height: VIEWER_BAR_ROW_PX }}>
        <Button asChild variant="ghost" size="icon" className="-ml-2 shrink-0">
          <NovelInfoLink route={route} novelId={novelId} aria-label="작품 정보">
            <ChevronLeft aria-hidden />
          </NovelInfoLink>
        </Button>
        <div className="flex min-w-0 flex-1 flex-col">
          <p className="truncate text-sm font-semibold text-foreground">{episodeLabel}</p>
          <p className="truncate text-xs text-muted-foreground tabular-nums">{location}</p>
        </div>
        {extraAction}
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
