import { Button } from "@ai-character-chat/ui/components/button";
import { SheetTitle } from "@ai-character-chat/ui/components/sheet";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { MessageCircle } from "lucide-react";
import { useId, useRef, useState } from "react";
import { toast } from "sonner";

import type { ReportReasonCategory } from "@/entities/content";
import { NovelReadProgressSummary, toNovelReadProgress } from "@/entities/novel";
import {
  saveWebnovelReadingPosition,
  sendWebnovelReadingPositionKeepalive,
  toWebnovelReportErrorMessage,
  useReportWebnovelCommentMutation,
  useReportWebnovelMutation,
  useWebnovelCommentsQuery,
  webnovelKeys,
  withWebnovelReadingPosition,
  WebnovelTocList,
  type WebnovelChapterItem,
  type WebnovelChapterResponse,
  type WebnovelDetailResponse,
} from "@/entities/webnovel";
import { WebnovelLikeButton } from "@/features/like-webnovel";
import { ReportContentModal } from "@/features/report-content";
import { WebnovelCommentsSheet } from "@/features/webnovel-comments";
import { formatCompactCount } from "@/shared/lib/number/formatCompactCount";
import {
  EpisodeReader,
  ViewerTocSheet,
  type EpisodeEndFormat,
  type ReadingPositionStore,
  type ViewerChapter,
} from "@/widgets/novel-viewer";

type WebnovelViewerProps = {
  novel: WebnovelDetailResponse;
  /** 지금 화의 목차 항목(읽던 자리). 화 조회 응답에도 자리가 실리지만, 떠날 때 먼저 써 두는 곳이 작품 정보 캐시라
   * 같은 화로 곧 돌아올 때 맞는 쪽은 이것이다. */
  summary: WebnovelChapterItem;
  /** 지금 화. 읽을 수 있는 화(본문이 실린)만 온다. */
  chapter: WebnovelChapterResponse;
  paragraphs: readonly string[];
};

/** 노벨의 화 읽기 화면(`/webnovels/$novelId/episodes/$chapterId`). 내 소설과 같은 읽기 화면(`EpisodeReader` — 고정
 * 판형·바·보기 설정)이고, 다른 것은 링크 경로, 읽은 자리를 공개본 판(`edition`)과 함께 노벨 API 에 쓰는 것, 목차의
 * 가격 표식, 화 끝(작가의 말이 독자에게 보이고, 마지막 화에 편집 길이 없고, 잠긴 다음 화에 가격을 붙인다)이다.
 *
 * 노벨에만 있는 것: 화 댓글(위 바의 댓글 버튼과 화 끝 "댓글 12" — 판형 흐름 밖의 시트라 댓글 수가 쪽 수를 바꾸지
 * 않는다), 소설 좋아요(화 끝), 이 화 신고(화 끝 맨 아래 — 내가 공개한 소설에는 없다). 이 화면은 읽을 수 있는 화에서만
 * 그려지므로 댓글을 언제나 열 수 있다. */
export function WebnovelViewer({ novel, summary, chapter, paragraphs }: WebnovelViewerProps) {
  const queryClient = useQueryClient();
  const progressId = useId();
  const [isCommentsOpen, setIsCommentsOpen] = useState(false);
  // 신고 모달은 루트에 마운트돼 읽기 화면이 모르므로 열린 동안을 여기서 센다 — 그동안 Esc 는 모달만 닫는다.
  const [isReportOpen, setIsReportOpen] = useState(false);
  const commentsOpenerRef = useRef<HTMLElement | null>(null);
  // 화 끝 "댓글 12" 의 수 — 시트가 같은 쿼리의 첫 페이지를 읽는다.
  const commentCount = useWebnovelCommentsQuery(novel.id, chapter.id).data?.pages[0]?.totalCount;
  const commentLabel = commentCount === undefined ? "댓글" : `댓글 ${formatCompactCount(commentCount)}`;
  const reportNovel = useReportWebnovelMutation(novel.id);
  const reportComment = useReportWebnovelCommentMutation(novel.id);

  function openComments(opener: HTMLElement) {
    commentsOpenerRef.current = opener;
    setIsCommentsOpen(true);
  }

  /** 이 화 또는 그 화의 댓글 하나를 신고한다 — 사유 모달은 작품 신고와 같은 것이다. */
  async function openReport(title: string, send: (reasonCategory: ReportReasonCategory) => Promise<void>) {
    setIsReportOpen(true);
    try {
      await ReportContentModal.call({
        title,
        mutationFn: async (call, reasonCategory) => {
          try {
            await send(reasonCategory);
            toast.success("신고가 접수되었어요.");
            call.end();
          } catch (error) {
            toast.error(toWebnovelReportErrorMessage(error));
          }
        },
      });
    } finally {
      setIsReportOpen(false);
    }
  }
  const { edition } = chapter;
  const position = summary.readingPosition;
  const chapters = novel.chapters.map(toViewerChapter);

  const readingPosition: ReadingPositionStore = {
    saved: position ?? undefined,
    // 노벨 목차는 화마다 읽던 자리를 언제나 싣는다(없으면 null) — 없다는 것을 확신할 수 있다.
    isAbsenceKnown: true,
    wasFinished: position?.finished ?? false,
    save: (next) => saveWebnovelReadingPosition(novel.id, chapter.id, { ...next, edition }),
    sendKeepalive: (next) => sendWebnovelReadingPositionKeepalive(novel.id, chapter.id, { ...next, edition }),
    onLeave(lastRecorded, settled) {
      if (lastRecorded !== undefined) {
        queryClient.setQueryData<WebnovelDetailResponse>(webnovelKeys.detail(novel.id), (detail) =>
          withWebnovelReadingPosition(detail, chapter.id, { ...lastRecorded, edition }),
        );
      }
      void settled.then(() => queryClient.invalidateQueries({ queryKey: webnovelKeys.detail(novel.id) }));
    },
  };

  return (
    <>
      <EpisodeReader
        route="public"
        isExtraSheetOpen={isCommentsOpen || isReportOpen}
        topBarAction={
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={commentLabel}
            className="shrink-0"
            onClick={(event) => openComments(event.currentTarget)}
          >
            <MessageCircle aria-hidden />
          </Button>
        }
        endExtras={{
          renderActions: (format: EpisodeEndFormat) => (
            <>
              <WebnovelLikeButton
                novelId={novel.id}
                liked={novel.liked}
                likeCount={novel.likeCount}
                className={format.buttonClassName}
                iconClassName={format.iconClassName}
              />
              <Button
                type="button"
                variant="ghost"
                className={cn("tabular-nums hover:bg-secondary", format.buttonClassName)}
                onClick={(event) => openComments(event.currentTarget)}
              >
                <MessageCircle aria-hidden className={format.iconClassName} />
                {commentLabel}
              </Button>
            </>
          ),
          renderReport: (format: EpisodeEndFormat) =>
            novel.isPublisher ? null : (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className={cn(
                  "text-muted-foreground hover:bg-secondary",
                  format.isInPageFormat && "h-[32px] px-[12px] text-[14px]",
                )}
                onClick={() =>
                  void openReport("노벨 신고하기", (reasonCategory) => reportNovel.mutateAsync({ reasonCategory, chapterId: chapter.id }))
                }
              >
                이 화 신고하기
              </Button>
            ),
        }}
        novel={{ id: novel.id, title: novel.title, chapters }}
        episode={{
          id: chapter.id,
          ordinal: chapter.ordinal,
          title: chapter.title,
          authorNote: chapter.authorNote ?? "",
          paragraphs,
        }}
        readingPosition={readingPosition}
        renderToc={(sheet) => (
          <ViewerTocSheet
            {...sheet}
            descriptionId={progressId}
            heading={
              <NovelReadProgressSummary
                heading={<SheetTitle>목차</SheetTitle>}
                progress={toNovelReadProgress(
                  novel.chapters.map((item) => ({ ...item, finishedReading: item.readingPosition?.finished ?? false })),
                )}
                labelId={progressId}
              />
            }
          >
            <WebnovelTocList
              novelId={novel.id}
              chapters={novel.chapters}
              lastReadChapterId={novel.lastRead?.chapterId}
              currentChapterId={chapter.id}
              surface="sheet"
              onNavigate={() => sheet.onOpenChange(false)}
            />
          </ViewerTocSheet>
        )}
      />
      <WebnovelCommentsSheet
        novelId={novel.id}
        chapterId={chapter.id}
        episodeLabel={`${chapter.ordinal}화`}
        open={isCommentsOpen}
        onOpenChange={setIsCommentsOpen}
        returnFocusTo={() => commentsOpenerRef.current}
        onReport={(commentId) =>
          void openReport("댓글 신고하기", (reasonCategory) => reportComment.mutateAsync({ commentId, reasonCategory }))
        }
      />
    </>
  );
}

/** 목차 항목을 읽기 화면의 화 모양으로. 아직 소장하지 않은 화만 가격을 싣는다(화 끝 "다음 화"가 미리 알린다). */
function toViewerChapter(item: WebnovelChapterItem): ViewerChapter {
  return {
    id: item.id,
    ordinal: item.ordinal,
    title: item.title,
    lockedPrice: item.access === "locked" && item.price !== null ? item.price : undefined,
  };
}
