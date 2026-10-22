import { Button } from "@ai-character-chat/ui/components/button";
import { SheetTitle } from "@ai-character-chat/ui/components/sheet";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { MessageCircle } from "lucide-react";
import { useId, useRef, useState } from "react";
import { toast } from "sonner";

import type { ReportReasonCategory } from "@/entities/content";
import { NovelReadProgressSummary, toNovelReadProgress, toPublicViewerIllustrations } from "@/entities/novel";
import {
  saveWebnovelReadingPosition,
  sendWebnovelReadingPositionKeepalive,
  toEditionNotice,
  toWebnovelReportErrorMessage,
  useReportWebnovelCommentMutation,
  useReportWebnovelMutation,
  useWebnovelCommentsQuery,
  webnovelKeys,
  withWebnovelReadingPosition,
  WebnovelTocList,
  type EditionNotice,
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

import { EditionChangesDialog } from "./EditionChangesDialog";

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
 * 그려지므로 댓글을 열 수 있다 — 판매를 멈춘 소설만 빼고(소장자만 열고, 댓글·좋아요·신고는 닫혀 있다). */
export function WebnovelViewer({ novel, summary, chapter, paragraphs }: WebnovelViewerProps) {
  const queryClient = useQueryClient();
  const progressId = useId();
  const [isCommentsOpen, setIsCommentsOpen] = useState(false);
  // 신고 모달은 루트에 마운트돼 읽기 화면이 모르므로 열린 동안을 여기서 센다 — 그동안 Esc 는 모달만 닫는다.
  const [isReportOpen, setIsReportOpen] = useState(false);
  // 판 안내의 "바뀐 내용" 다이얼로그. 열린 동안 Esc 는 다이얼로그만 닫는다(신고 모달과 같다).
  const [isEditionChangesOpen, setIsEditionChangesOpen] = useState(false);
  const editionChangesOpenerRef = useRef<HTMLElement | null>(null);
  const commentsOpenerRef = useRef<HTMLElement | null>(null);
  // 판매를 멈춘 소설(소장자만 연다)은 댓글·좋아요·신고가 닫혀 있다(서버가 404) — 그 자리를 그리지 않고 댓글도 묻지
  // 않는다.
  const isSalesStopped = chapter.salesStopped === true;
  // 화 끝 "댓글 12" 의 수 — 시트가 같은 쿼리의 첫 페이지를 읽는다.
  const commentCount = useWebnovelCommentsQuery(novel.id, chapter.id, { enabled: !isSalesStopped }).data?.pages[0]
    ?.totalCount;
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
  // 산 뒤 고쳐진 화면 제목 아래에 판 안내 한 줄. 없으면 머리에 아무것도 더하지 않는다(판형 쪽 수가 지금과 같다). 두 판의
  // 날짜·요약은 판형 밖의 "바뀐 내용" 다이얼로그가 맡는다 — 한 줄에 펴면 첫 쪽이 밀려 쪽 수가 바뀐다.
  const editionNotice = toEditionNotice(chapter);
  const position = summary.readingPosition;
  const chapters = novel.chapters.map((item) => toViewerChapter(item, isSalesStopped));

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
        isExtraSheetOpen={isCommentsOpen || isReportOpen || isEditionChangesOpen}
        headerNote={
          editionNotice === undefined ? undefined : (
            <EditionNoteLine
              novelId={novel.id}
              chapterId={chapter.id}
              notice={editionNotice}
              onOpenChanges={(opener) => {
                editionChangesOpenerRef.current = opener;
                setIsEditionChangesOpen(true);
              }}
            />
          )
        }
        topBarAction={
          isSalesStopped ? undefined : (
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
          )
        }
        endExtras={
          isSalesStopped
            ? undefined
            : {
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
              }
        }
        novel={{ id: novel.id, title: novel.title, chapters }}
        episode={{
          id: chapter.id,
          ordinal: chapter.ordinal,
          title: chapter.title,
          authorNote: chapter.authorNote ?? "",
          paragraphs,
          illustrations: toPublicViewerIllustrations(chapter),
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
              isSalesStopped={isSalesStopped}
            />
          </ViewerTocSheet>
        )}
      />
      {editionNotice?.latest !== undefined && (
        <EditionChangesDialog
          open={isEditionChangesOpen}
          onOpenChange={setIsEditionChangesOpen}
          novelId={novel.id}
          chapterId={chapter.id}
          ordinal={chapter.ordinal}
          purchased={editionNotice.purchased}
          latest={editionNotice.latest}
          isReadingPurchased={editionNotice.kind === "readingPurchased"}
          returnFocusTo={() => editionChangesOpenerRef.current}
        />
      )}
      {!isSalesStopped && (
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
      )}
    </>
  );
}

const EDITION_LINK_CLASS =
  "text-foreground underline underline-offset-2 outline-none focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-ring";

/** 화 제목 아래 판 안내 — 산 뒤 고쳐진 화를 연 소장자에게, 지금 읽는 판과 다른 판으로 가는 길과 두 판의 "바뀐 내용"을
 * 여는 버튼을 낸다. 고른 판은 주소의 `edition` 이라 같은 화면에서 search 만 바꾼다(판이 바뀌면 읽기 화면이 새로
 * 마운트된다). 최신 판 칸을 모르는 옛 서버면 "바뀐 내용"이 없다(보일 날짜·요약이 없다). */
function EditionNoteLine({
  novelId,
  chapterId,
  notice,
  onOpenChanges,
}: {
  novelId: string;
  chapterId: string;
  notice: EditionNotice;
  onOpenChanges: (opener: HTMLElement) => void;
}) {
  const params = { novelId, chapterId };
  const purchasedLabel = `구매 당시 판(${notice.purchased.dateLabel} 공개)`;
  const changesButton = notice.latest !== undefined && (
    <>
      {" · "}
      <button type="button" className={EDITION_LINK_CLASS} onClick={(event) => onOpenChanges(event.currentTarget)}>
        바뀐 내용
      </button>
    </>
  );
  return notice.kind === "newerAvailable" ? (
    <>
      소장하신 뒤 고쳐진 화예요.{" "}
      <Link to="/webnovels/$novelId/episodes/$chapterId" params={params} search={{ edition: notice.purchased.edition }} className={EDITION_LINK_CLASS}>
        {purchasedLabel}으로 읽기
      </Link>
      {changesButton}
    </>
  ) : (
    <>
      {purchasedLabel}을 읽고 있어요.{" "}
      <Link to="/webnovels/$novelId/episodes/$chapterId" params={params} search={{}} className={EDITION_LINK_CLASS}>
        최신 판으로 읽기
      </Link>
      {changesButton}
    </>
  );
}

/** 목차 항목을 읽기 화면의 화 모양으로. 아직 소장하지 않은 화만 가격을 싣는다(화 끝 "다음 화"가 미리 알린다). 판매를
 * 멈춘 소설이면 살 수 없으니 가격을 달지 않는다 — 누르면 잠긴 화 화면이 이유를 말한다. */
function toViewerChapter(item: WebnovelChapterItem, isSalesStopped: boolean): ViewerChapter {
  return {
    id: item.id,
    ordinal: item.ordinal,
    title: item.title,
    lockedPrice: !isSalesStopped && item.access === "locked" && item.price !== null ? item.price : undefined,
  };
}
