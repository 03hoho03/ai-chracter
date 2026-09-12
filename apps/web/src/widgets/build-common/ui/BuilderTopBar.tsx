import type { ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";

import { builderMainMaxWidth } from "../lib/builderMainMaxWidth";

type BuilderTopBarProps = {
  /** 빌더 라우트(`/builder`, `/builder/$type/$draftId`)의 페이지 제목. */
  title: string;
  /** 미리보기/임시저장/발행 같은 우측 액션 버튼들. 액션이 없는 화면(`BuilderTypeSelectPage`)에서는
   * 생략한다. */
  actions?: ReactNode;
  /** "변경사항은 자동으로 저장돼요." 같은 저장 계약 안내문. 폼이 있는 셸에서만 의미가 있다. */
  autosaveNotice?: string;
  /** builder-preview-validation 회귀 수정 — `BuilderLayout`에 넘기는 것과 같은 값을 그대로 넘겨야
   * 상단바와 `main`의 왼쪽 좌표가 모든 폭에서 같은 식(`builderMainMaxWidth`)으로 계산된다.
   * `BuilderLayout`을 쓰지 않는 화면(`BuilderTypeSelectPage`, 스켈레톤/에러 상태)은 생략한다. */
  isPreviewOpen?: boolean;
};

/**
 * builder-preview-validation(피드백 2) — 빌더 라우트는 전역 Header(`routes/__root.tsx`) 대신 이
 * 전용 상단바를 쓴다(크랙 실측 기준). 같은 56px(`h-14`) 자리를 차지하므로 BuilderLayout의
 * `calc(100dvh-3.5rem)` 높이 계산이 그대로 유지된다 — 헤더 자리만 바뀌고 높이 계산식은 그대로다.
 *
 * 뒤로가기 목적지는 인터뷰로 확정된 `/my`(내 작품) 하나뿐이라 prop으로 받지 않는다. 폭이 좁을 때는
 * 액션 버튼의 라벨을 숨기고 아이콘만 남긴다(`ContentTypeToggle`과 같은 `hidden sm:inline` 선례).
 */
export function BuilderTopBar({ title, actions, autosaveNotice, isPreviewOpen }: BuilderTopBarProps) {
  return (
    <header className="sticky top-0 z-30 h-14 shrink-0 border-b border-border bg-background">
      <div
        className={cn(
          "mx-auto flex h-14 items-center gap-2 px-4 sm:gap-3 sm:px-6",
          builderMainMaxWidth(isPreviewOpen),
        )}
      >
        <Button asChild variant="ghost" size="icon" aria-label="뒤로가기" className="shrink-0">
          <Link to="/my">
            <ArrowLeft aria-hidden className="size-4" />
          </Link>
        </Button>
        <h1 className="shrink-0 truncate text-xl font-semibold tracking-tight text-foreground">
          {title}
        </h1>
        <div className="min-w-0 flex-1">
          {!!autosaveNotice && <p className="truncate text-xs text-muted-foreground">{autosaveNotice}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">{actions}</div>}
      </div>
    </header>
  );
}
