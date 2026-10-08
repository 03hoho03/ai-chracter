import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { ReactNode, Ref } from "react";

import type { NovelChapterSummary } from "@/entities/novel";

type ViewerBottomBarProps = {
  ref: Ref<HTMLDivElement>;
  id: string;
  novelId: string;
  ordinal: number;
  totalCount: number;
  /** 화 안 진행률(0 … 1). */
  progress: number;
  previous: NovelChapterSummary | undefined;
  next: NovelChapterSummary | undefined;
  isVisible: boolean;
  /** 열려 있으면 아래 바 위에 붙여 그리는 보기 설정 패널. */
  settingsPanel: ReactNode;
};

/** 읽기 화면의 아래 바 — 이전 화 · 진행률 · 다음 화. 위 가장자리의 얇은 막대는 화 안에서 어디쯤인지 보이는 위치
 * 표시라 길이 변화에 전환을 두지 않는다(수치는 가운데 글자가 진다). 보기 설정 패널은 이 바 위에 붙어 함께
 * 오르내린다. 첫 화·마지막 화에서 막힌 쪽 버튼은 `aria-disabled` 다 — `disabled` 는 포커스를 빼앗아 키보드 사용자가
 * 자리를 잃는다. 이유는 화 번호가 말하므로 문구를 붙이지 않는다. */
export function ViewerBottomBar({
  ref,
  id,
  novelId,
  ordinal,
  totalCount,
  progress,
  previous,
  next,
  isVisible,
  settingsPanel,
}: ViewerBottomBarProps) {
  const percent = Math.round(progress * 100);

  return (
    <div
      ref={ref}
      id={id}
      inert={!isVisible}
      className={cn(
        "fixed inset-x-0 bottom-0 z-30 bg-background ease-out motion-safe:transition-[transform,opacity] motion-safe:duration-200",
        !isVisible && "translate-y-full opacity-0",
      )}
    >
      {settingsPanel}
      <nav aria-label="화 이동" className="border-t border-border pb-4-safe">
        <div aria-hidden className="h-0.5 bg-secondary">
          <div className="h-full bg-foreground" style={{ width: `${percent}%` }} />
        </div>
        <div className="flex items-center justify-between gap-2 px-4 pt-3 sm:px-6">
          <EpisodeStepButton novelId={novelId} target={previous} direction="previous" />
          <p className="text-xs text-muted-foreground tabular-nums">
            {ordinal}/{totalCount}화 · {percent}%
          </p>
          <EpisodeStepButton novelId={novelId} target={next} direction="next" />
        </div>
      </nav>
    </div>
  );
}

function EpisodeStepButton({
  novelId,
  target,
  direction,
}: {
  novelId: string;
  target: NovelChapterSummary | undefined;
  direction: "previous" | "next";
}) {
  const label = direction === "previous" ? "이전 화" : "다음 화";
  const content =
    direction === "previous" ? (
      <>
        <ChevronLeft aria-hidden />
        {label}
      </>
    ) : (
      <>
        {label}
        <ChevronRight aria-hidden />
      </>
    );

  if (target === undefined) {
    return (
      <Button type="button" variant="ghost" size="sm" aria-disabled className="aria-disabled:opacity-65">
        {content}
      </Button>
    );
  }
  return (
    <Button asChild variant="ghost" size="sm">
      <Link to="/novels/$novelId/episodes/$chapterId" params={{ novelId, chapterId: target.id }}>
        {content}
      </Link>
    </Button>
  );
}
