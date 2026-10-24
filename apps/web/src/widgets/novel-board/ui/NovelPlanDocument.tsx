import { cn } from "@ai-character-chat/ui/lib/utils";
import { useRef, useState, type RefObject } from "react";

import { useNovelOutlineQuery, useNovelSourceSelectionQuery, type NovelDetailResponse } from "@/entities/novel";
import type { NovelChapterJobFlow } from "@/features/create-novel-chapter";
import {
  NovelEpisodesStep,
  NovelOutlineStep,
  toOutlineBase,
  type OutlineMakeControl,
  type OutlineRange,
} from "@/features/plan-novel-outline";
import { NovelSourceSelectionStep, toSourceSelectionStatus } from "@/features/select-novel-source";

import { toCurrentPlanStep } from "../model/planStep";

import { usePlanTurns } from "./usePlanTurns";

type NovelPlanDocumentProps = {
  novel: NovelDetailResponse;
  /** 화 작업 흐름 — 구성안 만들기(유료)도 이 흐름으로 시작하고, 진행·다시 시도는 작업 줄이 진다. */
  chapterFlow: NovelChapterJobFlow;
  /** 문서 제목. 구성 모드로 옮기면 호출부가 여기로 포커스를 보낸다. */
  headingRef: RefObject<HTMLHeadingElement | null>;
  /** 3단계의 화 하나(장면 구성안·원고)를 연다. */
  onOpenEpisode: (episodeKey: string) => void;
  /** 원고가 된 화를 보드에서 고른다. */
  onOpenChapter: (chapterId: string) => void;
  onDraftDirtyChange: (isDirty: boolean) => void;
};

/** 구성 단계. 차례가 곧 정보라(앞 단계를 승인해야 다음 단계가 이어진다) 번호를 단다. */
const STEPS = ["담을 대화", "전체 구성안", "화별 장면·원고"] as const;

/**
 * 편집 보드의 구성 모드(`?select=plan`) — 대화를 골라 화 구성을 세우는 한 열 문서. 넓은 화면에서도 캔버스·옆 패널 대신 이
 * 문서 하나가 보이고(폭은 호출부가 정한다), 상단바·작업 줄·떠날 때의 버림 확인은 보드 것을 그대로 쓴다.
 *
 * 단계는 셋이다 — 담을 대화, 전체 구성안, 화별 장면·원고(화 목록 — 화 하나는 `?select=plan:{화 키}` 화면). 앞 두 단계는 서로 다른
 * 기능이라 이 문서가 잇는다 — 구성안 단계의 근거 턴 번호는 담을 대화 단계와 같은 묶기로 세고(같은 대화방 메시지 캐시), 낡은 구성안의
 * "구간 되돌리기"는 담을 대화 단계에 고침으로 넘긴다.
 */
export function NovelPlanDocument({
  novel,
  chapterFlow,
  headingRef,
  onOpenEpisode,
  onOpenChapter,
  onDraftDirtyChange,
}: NovelPlanDocumentProps) {
  const isRoomGone = novel.chatRoomId === null;
  const selectionQuery = useNovelSourceSelectionQuery(novel.id, { enabled: !isRoomGone });
  const outlineQuery = useNovelOutlineQuery(novel.id, { enabled: true });
  const { turns, isTurnsFailed } = usePlanTurns(novel);
  const [restoreRequest, setRestoreRequest] = useState<
    { id: number; ranges: OutlineRange[]; isExact: boolean } | undefined
  >(undefined);
  // 두 단계가 따로 알리는 저장하지 않은 고침. 어느 쪽이든 있으면 보드가 옮기기 전에 버릴지 묻는다.
  const dirtyRef = useRef({ selection: false, outline: false });

  const selectionState = selectionQuery.data;
  const outlineBase = outlineQuery.data === undefined ? undefined : toOutlineBase(outlineQuery.data);
  const currentStep = toCurrentPlanStep({
    selection: selectionState === undefined ? undefined : toSourceSelectionStatus(selectionState),
    outline: outlineBase?.status,
    isOutlineStale: outlineBase?.isStale,
  });
  const make: OutlineMakeControl = {
    onStart: () => void chapterFlow.startOutline(),
    isPreparing: chapterFlow.preparing === "outline",
    // 다른 버튼에서 시작한 준비(경계 고르기·다시 만들기 확인)도 진행 중인 작업처럼 막는다.
    isJobRunning: chapterFlow.isJobRunning || (chapterFlow.preparing !== undefined && chapterFlow.preparing !== "outline"),
    isOutlineJobRunning: chapterFlow.runningKind === "outline_generate",
    isAiEditRunning: chapterFlow.isAiEditRunning,
    statusId: chapterFlow.statusId,
  };

  function reportDirty(part: "selection" | "outline", isDirty: boolean) {
    dirtyRef.current = { ...dirtyRef.current, [part]: isDirty };
    onDraftDirtyChange(dirtyRef.current.selection || dirtyRef.current.outline);
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-3">
        {/* 조작 대상이 아니라 포커스를 받아 두는 자리라 `tabIndex=-1` 이고 포커스 테두리를 그리지 않는다. */}
        <h2 ref={headingRef} tabIndex={-1} className="text-xl font-semibold tracking-tight text-foreground outline-none">
          구성
        </h2>
        <p className="text-sm break-keep text-muted-foreground">
          소설에 담을 대화를 고르고 승인하면, 그 대화로 화 구성을 세워 화마다 원고를 써요.
        </p>
        <ol aria-label="구성 단계" className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
          {STEPS.map((step, index) => (
            <li
              key={step}
              aria-current={index === currentStep ? "step" : undefined}
              className={cn(
                "flex items-center gap-1.5",
                index === currentStep ? "font-medium text-foreground" : "text-muted-foreground",
              )}
            >
              <span
                aria-hidden
                className={cn(
                  "flex size-5 items-center justify-center rounded-full border text-xs tabular-nums",
                  index === currentStep ? "border-foreground" : "border-border",
                )}
              >
                {index + 1}
              </span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      </div>
      <NovelSourceSelectionStep
        novel={novel}
        onDraftDirtyChange={(isDirty) => reportDirty("selection", isDirty)}
        restoreRequest={restoreRequest}
        // 담을 대화 탓으로 거절·실패한 구성안·장면 구성안·원고의 작업 줄 오류는 다시 승인하면 원인이 풀린다.
        onApproved={chapterFlow.clearSelectionChangedNotice}
      />
      <NovelOutlineStep
        novel={novel}
        turns={turns}
        isTurnsFailed={isTurnsFailed}
        selection={
          selectionState === undefined
            ? undefined
            : { hasApproved: selectionState.approved !== null, hasPendingDraft: selectionState.draft !== null }
        }
        make={make}
        onRevertSelection={(revert) =>
          setRestoreRequest((previous) => ({
            id: (previous?.id ?? 0) + 1,
            ranges: revert.ranges,
            isExact: revert.kind === "exact",
          }))
        }
        onDraftDirtyChange={(isDirty) => reportDirty("outline", isDirty)}
      />
      <NovelEpisodesStep novel={novel} onOpenEpisode={onOpenEpisode} onOpenChapter={onOpenChapter} />
    </div>
  );
}
