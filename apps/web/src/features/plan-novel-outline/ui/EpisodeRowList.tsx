import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { BookOpen, ChevronRight } from "lucide-react";
import { useId } from "react";

import {
  MANUSCRIPT_STATUS_LABEL,
  SCENE_OUTLINE_STATUS_LABEL,
  type ManuscriptStatus,
  type SceneOutlineStatus,
} from "../model/episodeStatus";

export type EpisodeRow = {
  key: string;
  ordinal: number;
  title: string;
  sceneOutline: SceneOutlineStatus;
  manuscript: ManuscriptStatus;
};

type EpisodeRowListProps = {
  rows: readonly EpisodeRow[];
  /** 그 화의 장면 구성안·원고 화면을 연다. */
  onOpenEpisode: (episodeKey: string) => void;
  /** 원고가 된 화를 보드에서 고른다. */
  onOpenChapter: (chapterId: string) => void;
};

/**
 * 구성 3단계의 화 목록 — 승인한 전체 구성안의 화마다 한 줄. 장면 구성안 상태와 원고 상태를 윤곽 배지로 달고, "열기"로 그 화의 장면
 * 구성안·원고 화면에 들어간다. 원고가 된 화에는 보드의 그 화로 가는 버튼을 함께 둔다.
 *
 * 배지는 상태라 윤곽이다. 이용자가 할 일이 생긴 상태(쓸 차례·낡음)만 잉크를 밝힌다 — 색으로 가르지 않는다.
 */
export function EpisodeRowList({ rows, onOpenEpisode, onOpenChapter }: EpisodeRowListProps) {
  return (
    <ol aria-label="화별 장면·원고" className="flex flex-col gap-2">
      {rows.map((row) => (
        <EpisodeRowItem key={row.key} row={row} onOpenEpisode={onOpenEpisode} onOpenChapter={onOpenChapter} />
      ))}
    </ol>
  );
}

function EpisodeRowItem({
  row,
  onOpenEpisode,
  onOpenChapter,
}: {
  row: EpisodeRow;
  onOpenEpisode: (episodeKey: string) => void;
  onOpenChapter: (chapterId: string) => void;
}) {
  const headingId = useId();
  const label = `${row.ordinal}화`;
  const { manuscript } = row;
  return (
    <li
      aria-labelledby={headingId}
      data-plan-episode={row.key}
      className="flex flex-col gap-2 rounded-xl border border-border px-4 py-3"
    >
      <h4 id={headingId} className="text-sm font-semibold break-keep text-foreground">
        <span className="text-muted-foreground tabular-nums">{label}</span> ·{" "}
        {row.title.trim() === "" ? "제목 없음" : row.title}
      </h4>
      <div className="flex flex-wrap items-center gap-1.5">
        <StatusBadge label={SCENE_OUTLINE_STATUS_LABEL[row.sceneOutline]} isActionable={row.sceneOutline === "stale"} />
        <StatusBadge label={MANUSCRIPT_STATUS_LABEL[manuscript.kind]} isActionable={manuscript.kind === "next"} />
        <div className="ml-auto flex flex-wrap gap-1.5">
          {manuscript.kind === "written" && (
            <Button type="button" variant="ghost" size="sm" onClick={() => onOpenChapter(manuscript.chapterId)}>
              <BookOpen aria-hidden />
              {label} 보기
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-label={`${label} 장면·원고 열기`}
            onClick={() => onOpenEpisode(row.key)}
          >
            열기
            <ChevronRight aria-hidden />
          </Button>
        </div>
      </div>
    </li>
  );
}

function StatusBadge({ label, isActionable }: { label: string; isActionable: boolean }) {
  return (
    <span
      className={cn(
        "rounded-full border border-border px-2 py-0.5 text-badge font-medium",
        isActionable ? "text-foreground" : "text-muted-foreground",
      )}
    >
      {label}
    </span>
  );
}
