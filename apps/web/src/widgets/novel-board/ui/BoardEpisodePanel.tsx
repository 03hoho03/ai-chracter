import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { BookOpen, CloudOff, History, PencilLine, Trash2 } from "lucide-react";
import { useEffect, useId, useState, type RefObject } from "react";

import {
  chaptersInBatch,
  toEpisodeRangeLabel,
  useNovelChapterQuery,
  type NovelChapterSummary,
  type NovelDetailResponse,
} from "@/entities/novel";
import { RegenerateChapterButton, type NovelChapterJobFlow } from "@/features/create-novel-chapter";
import { DeleteLastChapterModal } from "@/features/delete-novel";
import { AiEditStatus, NovelChapterText, type NovelAiEditFlow } from "@/features/edit-novel-chapter";
import { AuthorNoteEditor, EpisodeTitleEditor } from "@/features/edit-novel-episode";
import { NovelRevisionHistoryModal } from "@/features/novel-revision-history";

type BoardEpisodePanelProps = {
  novel: NovelDetailResponse;
  chapter: NovelChapterSummary;
  chapterFlow: NovelChapterJobFlow;
  aiEdit: NovelAiEditFlow;
  /** 화 머리(`h2`). 화를 고르면 호출부가 여기로 포커스를 보낸다. */
  headingRef: RefObject<HTMLHeadingElement | null>;
  /** 마지막 묶음을 지운 뒤. 지운 화들 중 첫 화의 번호와 지운 화들을 넘긴다 — 호출부가 그 앞 화(새 마지막 화)를 고르고,
   * 옮긴 뒤 지운 화들의 캐시를 버린다. */
  onChapterDeleted: (firstDeletedOrdinal: number, deletedChapterIds: string[]) => void;
  /** 직접 고치던 글이 시작할 때와 달라졌는가. 호출부가 다른 것을 고르기 전에 확인을 받는 데 쓴다. */
  onDraftDirtyChange: (isDirty: boolean) => void;
};

/**
 * 편집 패널의 화 하나 — 화 머리(제목 고치기·글자 수·판), 동작 줄(고치기·판 이력·읽기 화면), AI 생성 고지, AI 수정
 * 진행, 본문(문단 고르기·AI 수정·직접 고치기), 작가의 말, 그리고 이 화가 든 묶음의 동작(다시 만들기·마지막 묶음
 * 지우기). 화마다 새로 마운트된다(호출부가 고른 것으로 `key` 를 준다) — 고치기 모드와 고른 문단은 그 화에만 속한다.
 *
 * 이 화면의 유일한 솔리드 채움은 상단 바의 "다음 화 만들기"라 여기 버튼은 전부 테두리·회색·틴트다.
 */
export function BoardEpisodePanel({
  novel,
  chapter,
  chapterFlow,
  aiEdit,
  headingRef,
  onChapterDeleted,
  onDraftDirtyChange,
}: BoardEpisodePanelProps) {
  const deleteReasonId = useId();
  const batchHeadingId = useId();
  const [isFixMode, setIsFixMode] = useState(false);
  const chapterQuery = useNovelChapterQuery(novel.id, chapter.id, chapter.currentRevisionId);
  // 지우기는 마지막에 한 번에 만든 화들(마지막 묶음) 단위다 — 그 묶음의 어느 화에서든 지울 수 있고, 함께 지워지는
  // 화들의 범위를 버튼이 말한다.
  const lastChapter = novel.chapters.reduce<NovelChapterSummary | undefined>(
    (latest, item) => (latest === undefined || item.ordinal > latest.ordinal ? item : latest),
    undefined,
  );
  const isLastBatch = lastChapter !== undefined && chapter.batchId === lastChapter.batchId;
  const batch = novel.batches.find((item) => item.id === chapter.batchId);
  const batchChapters = chaptersInBatch(novel.chapters, chapter.batchId);
  const firstInBatch = batchChapters[0] ?? chapter;
  const lastInBatch = batchChapters.at(-1) ?? chapter;
  const batchRangeLabel = toEpisodeRangeLabel(firstInBatch.ordinal, lastInBatch.ordinal);
  // 진행 중 작업이 있으면 서버가 마지막 묶음 지우기를 409 로 막는다 — 미리 막고 까닭을 말한다.
  const isDeleteBlocked = novel.activeJob !== null || chapterFlow.isBusy || aiEdit.isRunning;
  const hasPendingAiEdits = novel.pendingAiEdits.some((edit) => edit.chapterId === chapter.id);
  const revision = chapterQuery.data?.revision;

  // 판 이력 모달은 루트에 마운트돼 화를 옮겨도 남는다 — 이 화를 떠나면(다른 카드 고르기·작업이 끝난 뒤의 자동 이동·
  // 화면 이탈) 이 화의 이력을 닫는다. 남겨 두면 다른 화를 보면서 옛 화의 이력을 보게 된다.
  useEffect(() => () => NovelRevisionHistoryModal.end(null), []);

  function focusHeading() {
    headingRef.current?.focus();
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <EpisodeTitleEditor novel={novel} chapter={chapter} headingRef={headingRef} />
        <p className="text-sm text-muted-foreground tabular-nums">
          {chapter.charCount.toLocaleString()}자{revision !== undefined && ` · ${revision.revisionNo}판`}
        </p>
        <div className="flex flex-wrap gap-2">
          {/* 모드 버튼은 라벨이 상태를 말한다 — 눌린 토글(유채색 채움)로 그리면 이 화면의 솔리드 채움이 둘이 된다. */}
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-disabled={chapterQuery.data === undefined}
            className="aria-disabled:opacity-65"
            onClick={() => {
              if (chapterQuery.data === undefined) return;
              // 고치기를 시작하면 지난 결과·거절 문장은 이제 이 동작과 상관없다.
              if (!isFixMode) aiEdit.report({ type: "started" });
              setIsFixMode((value) => !value);
            }}
          >
            <PencilLine aria-hidden />
            {isFixMode ? "고치기 끝내기" : "고치기"}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              void NovelRevisionHistoryModal.call({
                novelId: novel.id,
                chapterId: chapter.id,
                chapterOrdinal: chapter.ordinal,
                hasPendingAiEdits,
              }).then((restoredRevisionNo) => {
                if (restoredRevisionNo === null) return;
                aiEdit.report({ type: "restored", chapterOrdinal: chapter.ordinal, revisionNo: restoredRevisionNo });
                focusHeading();
              })
            }
          >
            <History aria-hidden />
            판 이력
          </Button>
          <Button asChild variant="ghost" size="sm">
            <Link to="/novels/$novelId/episodes/$chapterId" params={{ novelId: novel.id, chapterId: chapter.id }}>
              <BookOpen aria-hidden />
              읽기 화면
            </Link>
          </Button>
        </div>
        <p className="text-sm break-keep text-muted-foreground">AI가 대화를 바탕으로 생성한 글이에요.</p>
      </div>

      <AiEditStatus aiEdit={aiEdit} />

      <ChapterBody
        query={chapterQuery}
        novel={novel}
        isFixMode={isFixMode}
        aiEdit={aiEdit}
        onFocusFallback={focusHeading}
        onDraftDirtyChange={onDraftDirtyChange}
      />

      <AuthorNoteEditor novel={novel} chapter={chapter} />

      <section aria-labelledby={batchHeadingId} className="flex flex-col gap-3 border-t border-border pt-4">
        <h3 id={batchHeadingId} className="text-sm font-semibold text-foreground tabular-nums">
          {batch === undefined ? batchRangeLabel : `묶음 ${batch.ordinal} · ${batchRangeLabel}`}
        </h3>
        {/* 대화방이 지워진 소설은 다시 만들 수 없어(버튼이 없다) 다시 만들기 안내도 두지 않는다. */}
        {!chapterFlow.isRoomGone && (
          <p className="text-xs break-keep text-muted-foreground">
            {batchChapters.length > 1
              ? "한 번에 만든 화들이라 다시 만들거나 지울 때 함께 바뀌어요. 고친 화 제목은 다시 만들어도 그대로예요."
              : "다시 만들어도 고친 화 제목은 그대로예요."}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          {/* AI 수정을 준비·요청하는 동안과 202 뒤 상세를 다시 받기 전에는 상세에 진행 중 작업이 아직 없어 화 작업
              흐름이 모른다 — 이 패널이 아는 AI 수정 상태로 잠근다. 못 누르는 사유는 화 머리 아래 AI 수정 진행 줄이
              진다(준비·요청 중에는 그 줄이 비어 있어 사유를 달지 않는다). */}
          <RegenerateChapterButton
            flow={chapterFlow}
            chapter={chapter}
            chapters={novel.chapters}
            isBlocked={aiEdit.isPreparing || aiEdit.isRunning}
            blockedReasonId={aiEdit.isRunning ? aiEdit.statusId : undefined}
          />
          {isLastBatch && (
            <Button
              type="button"
              variant="destructive"
              size="sm"
              aria-disabled={isDeleteBlocked}
              aria-describedby={isDeleteBlocked ? deleteReasonId : undefined}
              className="aria-disabled:opacity-65"
              onClick={() => {
                if (isDeleteBlocked) return;
                void DeleteLastChapterModal.call({
                  novelId: novel.id,
                  batchId: chapter.batchId,
                  chapterIds: batchChapters.map((item) => item.id),
                  rangeLabel: batchRangeLabel,
                }).then((isDeleted) => {
                  if (isDeleted) onChapterDeleted(firstInBatch.ordinal, batchChapters.map((item) => item.id));
                });
              }}
            >
              <Trash2 aria-hidden />
              {batchChapters.length > 1 ? `${batchRangeLabel} 지우기` : "이 화 지우기"}
            </Button>
          )}
        </div>
        {isLastBatch && isDeleteBlocked && (
          <p id={deleteReasonId} className="text-sm break-keep text-muted-foreground">
            진행 중인 작업이 끝나면 지울 수 있어요.
          </p>
        )}
        {!isLastBatch && <p className="text-xs break-keep text-muted-foreground">지우기는 마지막 묶음만 할 수 있어요.</p>}
      </section>
    </div>
  );
}

type ChapterBodyProps = {
  query: ReturnType<typeof useNovelChapterQuery>;
  novel: NovelDetailResponse;
  isFixMode: boolean;
  aiEdit: NovelAiEditFlow;
  onFocusFallback: () => void;
  onDraftDirtyChange: (isDirty: boolean) => void;
};

/** 본문 로딩·실패·본문. 이미 받은 본문이 있으면 다시 받기가 실패해도 그대로 둔다. */
function ChapterBody({ query, novel, isFixMode, aiEdit, onFocusFallback, onDraftDirtyChange }: ChapterBodyProps) {
  if (query.data !== undefined) {
    return (
      <NovelChapterText
        novel={novel}
        chapter={query.data}
        isFixMode={isFixMode}
        aiEdit={aiEdit}
        onFocusFallback={onFocusFallback}
        onDraftDirtyChange={onDraftDirtyChange}
      />
    );
  }

  if (query.isError) {
    return (
      <div className="flex flex-col items-start gap-3 py-6">
        <p className="flex items-center gap-2 text-sm break-keep text-muted-foreground">
          <CloudOff aria-hidden className="size-4 shrink-0" />이 화를 불러오지 못했어요. 잠시 후 다시 시도해주세요.
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-disabled={query.isFetching}
          className="aria-disabled:opacity-65"
          onClick={() => {
            if (query.isFetching) return;
            void query.refetch();
          }}
        >
          다시 시도
        </Button>
      </div>
    );
  }

  return (
    <div aria-hidden className="flex max-w-prose flex-col gap-3">
      <div className="h-5 w-full animate-pulse rounded bg-muted" />
      <div className="h-5 w-11/12 animate-pulse rounded bg-muted" />
      <div className="h-5 w-4/5 animate-pulse rounded bg-muted" />
      <div className="h-5 w-full animate-pulse rounded bg-muted" />
      <div className="h-5 w-2/3 animate-pulse rounded bg-muted" />
    </div>
  );
}
