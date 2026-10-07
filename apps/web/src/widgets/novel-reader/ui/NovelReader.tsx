import { Button } from "@ai-character-chat/ui/components/button";
import { CloudOff, History, PencilLine, Trash2 } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

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
import { NovelRevisionHistoryModal } from "@/features/novel-revision-history";

type NovelReaderProps = {
  novel: NovelDetailResponse;
  chapter: NovelChapterSummary;
  chapterFlow: NovelChapterJobFlow;
  aiEdit: NovelAiEditFlow;
  /** 이 장 제목으로 포커스를 옮길 차례인가(새로 만든·다시 만든 장으로 옮겨 왔을 때). */
  shouldFocusHeading: boolean;
  onHeadingFocused: () => void;
  /** 마지막 화들을 지운 뒤. 지운 화들 중 첫 화의 번호를 넘긴다 — 화면이 그 앞 화(새 마지막 화)로 옮기고 그 제목에
   * 포커스를 둔다. */
  onChapterDeleted: (firstDeletedOrdinal: number) => void;
  /** 직접 고치던 글이 시작할 때와 달라졌는가. 화면이 장을 옮기기 전에 확인을 받는 데 쓴다. */
  onDraftDirtyChange: (isDirty: boolean) => void;
};

/** 장 하나를 읽고 고치는 자리 — 장 머리(제목·고치기·다시 만들기), AI 생성 고지, 진행 안내, 본문, 장 관리(판 이력·
 * 마지막 장 지우기). 장마다 새로 마운트된다(호출부가 장 id 로 `key` 를 준다) — 고치기 모드와 고른 문단은 그 장에만
 * 속한다.
 *
 * 장 안은 문서 스크롤이다. 고정 막대를 두지 않고, 모든 동작은 본문 흐름 안에 있다. 이 화면의 유일한 솔리드
 * 채움은 아래 "다음 장 만들기"라 여기 버튼은 전부 테두리·회색·틴트다. 복사·내보내기 버튼은 두지 않는다. */
export function NovelReader({
  novel,
  chapter,
  chapterFlow,
  aiEdit,
  shouldFocusHeading,
  onHeadingFocused,
  onChapterDeleted,
  onDraftDirtyChange,
}: NovelReaderProps) {
  const headingId = useId();
  const deleteReasonId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [isFixMode, setIsFixMode] = useState(false);
  const chapterQuery = useNovelChapterQuery(novel.id, chapter.id, chapter.currentRevisionId);
  // 지우기는 마지막에 한 번에 만든 화들(마지막 묶음) 단위다 — 그 묶음의 어느 화에서든 지울 수 있고, 함께 지워지는
  // 화들의 범위를 버튼이 말한다.
  const lastChapter = novel.chapters.reduce<NovelChapterSummary | undefined>(
    (latest, item) => (latest === undefined || item.ordinal > latest.ordinal ? item : latest),
    undefined,
  );
  const isLastChapter = lastChapter !== undefined && chapter.batchId === lastChapter.batchId;
  const batchChapters = chaptersInBatch(novel.chapters, chapter.batchId);
  const firstInBatch = batchChapters[0] ?? chapter;
  const lastInBatch = batchChapters.at(-1) ?? chapter;
  const batchRangeLabel = toEpisodeRangeLabel(firstInBatch.ordinal, lastInBatch.ordinal);
  // 진행 중 작업이 있으면 서버가 마지막 화 지우기를 409 로 막는다 — 미리 막고 까닭을 말한다.
  const isDeleteBlocked = novel.activeJob !== null || chapterFlow.isBusy || aiEdit.isRunning;
  const hasPendingAiEdits = novel.pendingAiEdits.some((edit) => edit.chapterId === chapter.id);

  // 판 이력 모달은 루트에 마운트돼 장을 옮겨도 남는다 — 이 장을 떠나면(목차·장 작업이 끝난 뒤의 자동 이동·화면
  // 이탈) 이 장의 이력을 닫는다. 남겨 두면 다른 장을 보면서 옛 장의 이력을 보게 된다.
  useEffect(() => () => NovelRevisionHistoryModal.end(null), []);

  useEffect(() => {
    if (!shouldFocusHeading) return;
    headingRef.current?.focus();
    onHeadingFocused();
    // `onHeadingFocused` 는 렌더마다 새로 만들어지는 화살표라 넣지 않는다 — 포커스 시점은 `shouldFocusHeading` 이 정한다.
  }, [shouldFocusHeading]);

  function focusHeading() {
    headingRef.current?.focus();
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* 조작 대상이 아니라 포커스를 받아 두는 자리라 `tabIndex=-1` 이고 포커스 테두리를 그리지 않는다. */}
          <h2 id={headingId} ref={headingRef} tabIndex={-1} className="text-lg font-semibold text-foreground outline-none">
            {chapter.title ? `${chapter.ordinal}화. ${chapter.title}` : `${chapter.ordinal}화`}
          </h2>
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
            {/* AI 수정을 준비·요청하는 동안과 202 뒤 상세를 다시 받기 전에는 상세에 진행 중 작업이 아직 없어 장 작업
                흐름이 모른다 — 이 화면이 아는 AI 수정 상태로 잠근다. 못 누르는 사유는 장 머리 바로 아래 AI 수정 진행
                줄이 진다(준비·요청 중에는 그 줄이 비어 있어 사유를 달지 않는다). */}
            <RegenerateChapterButton
              flow={chapterFlow}
              chapter={chapter}
              chapters={novel.chapters}
              isBlocked={aiEdit.isPreparing || aiEdit.isRunning}
              blockedReasonId={aiEdit.isRunning ? aiEdit.statusId : undefined}
            />
          </div>
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

      <div className="flex flex-col gap-1.5 border-t border-border pt-4">
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="ghost"
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
          {isLastChapter && (
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
                  if (isDeleted) onChapterDeleted(firstInBatch.ordinal);
                });
              }}
            >
              <Trash2 aria-hidden />
              {batchChapters.length > 1 ? `${batchRangeLabel} 지우기` : "이 화 지우기"}
            </Button>
          )}
        </div>
        {isLastChapter && isDeleteBlocked && (
          <p id={deleteReasonId} className="text-sm break-keep text-muted-foreground">
            진행 중인 작업이 끝나면 지울 수 있어요.
          </p>
        )}
      </div>
    </section>
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
