import type { RefObject } from "react";

import type { NovelDetailResponse } from "@/entities/novel";
import type { NovelChapterJobFlow } from "@/features/create-novel-chapter";
import { NovelEpisodePlanStep, type EpisodeJobControl } from "@/features/plan-novel-outline";

import { usePlanTurns } from "./usePlanTurns";

type NovelPlanEpisodeDocumentProps = {
  novel: NovelDetailResponse;
  episodeKey: string;
  /** 화 작업 흐름 — 장면 구성안 만들기·원고 쓰기(유료)도 이 흐름으로 시작하고, 진행·다시 시도는 작업 줄이 진다. */
  chapterFlow: NovelChapterJobFlow;
  headingRef: RefObject<HTMLHeadingElement | null>;
  onOpenChapter: (chapterId: string) => void;
  onDraftDirtyChange: (isDirty: boolean) => void;
};

/** 구성 모드의 화 하나(`?select=plan:{화 키}`) — 그 화의 장면 구성안과 원고. 구성 문서와 같은 한 열이고, 화 작업 흐름과 근거 턴을
 * 이어 준다. */
export function NovelPlanEpisodeDocument({
  novel,
  episodeKey,
  chapterFlow,
  headingRef,
  onOpenChapter,
  onDraftDirtyChange,
}: NovelPlanEpisodeDocumentProps) {
  const { turns, isTurnsFailed } = usePlanTurns(novel);
  const isPreparingHere = chapterFlow.preparingEpisodeKey === episodeKey;
  // 도는 작업의 화를 모르면(새로고침·다른 탭에서 시작) 이 화의 작업일 수도 있어 고치기를 막는다 — 끝나면 새 판이 올 수 있다.
  const isRunningHere = chapterFlow.runningEpisodeKey === null || chapterFlow.runningEpisodeKey === episodeKey;
  const control: EpisodeJobControl = {
    onMakeScenes: () => void chapterFlow.startEpisodeOutline(episodeKey),
    onWrite: () => void chapterFlow.startOutlineChapter(episodeKey),
    preparing:
      isPreparingHere && (chapterFlow.preparing === "episodeOutline" || chapterFlow.preparing === "outlineChapter")
        ? chapterFlow.preparing
        : undefined,
    // 다른 화·다른 버튼에서 시작한 준비(경계 고르기·다시 만들기·구성안 확인)도 진행 중인 작업처럼 막는다.
    isJobRunning: chapterFlow.isJobRunning || (chapterFlow.preparing !== undefined && !isPreparingHere),
    isSceneJobRunningHere: chapterFlow.runningKind === "episode_outline_generate" && isRunningHere,
    isWriteJobRunningHere: chapterFlow.runningKind === "outline_chapter_generate" && isRunningHere,
    isAiEditRunning: chapterFlow.isAiEditRunning,
    statusId: chapterFlow.statusId,
  };

  return (
    <NovelEpisodePlanStep
      novel={novel}
      episodeKey={episodeKey}
      turns={turns}
      isTurnsFailed={isTurnsFailed}
      headingRef={headingRef}
      control={control}
      onOpenChapter={onOpenChapter}
      onDraftDirtyChange={onDraftDirtyChange}
    />
  );
}
