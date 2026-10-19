import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { BookX, CloudOff, Eye, Sparkles } from "lucide-react";
import { useId } from "react";

import { NovelReadProgressSummary, NovelStatusState, toNovelReadProgress, toResumeTarget } from "@/entities/novel";
import {
  ReadingEndedState,
  toPublisherCredit,
  toSourceCredit,
  toWebnovelLoadFailure,
  toWebnovelPriceSummary,
  useWebnovelQuery,
  WebnovelCover,
  WebnovelSourceCredit,
  WebnovelTocList,
  WITHDRAWN_USER_LABEL,
  type WebnovelDetailResponse,
} from "@/entities/webnovel";
import { WebnovelLikeButton } from "@/features/like-webnovel";
import { formatCompactCount } from "@/shared/lib/number/formatCompactCount";

import { WebnovelActionsMenu } from "./WebnovelActionsMenu";

const PAGE_CLASS = "mx-auto flex max-w-2xl flex-col gap-8 px-4 sm:px-6 py-10";

/** `/webnovels/$novelId` — 노벨 작품 정보. 표지·제목·원작·게시자·가격, 읽기 시작, 소개, 목차(화마다 이 사람에게의
 * 가격 표식). 화면에 나가는 글은 공개 시점에 얼린 공개본 사본이다. 평범한 문서 스크롤 화면이라 전역 헤더와 사이트
 * 푸터가 있다. 소유자 작품 정보와 뼈대(표지 왼쪽 + 글 오른쪽)가 같지만 고치는 요소가 하나도 없다.
 *
 * 읽을 수 없는 소설은 소장했던 사람에게만 이유를 말하고(410), 나머지에게는 찾을 수 없다고만 한다(404).
 *
 * 판매를 멈춘 소설(목록에서 빠졌지만 소장자라 열린 것)은 그렇다고 한 줄로 말하고, 가격 대신 "판매 중지"를 적고,
 * 좋아요·⋯(신고)를 그리지 않는다 — 서버가 닫아 둔 길이다. 소장한 화와 무료 화는 그대로 읽는다. */
export function WebnovelInfoPage({ novelId }: { novelId: string }) {
  const query = useWebnovelQuery(novelId);

  if (query.isPending) {
    return (
      <main className={PAGE_CLASS}>
        <WebnovelInfoSkeleton />
      </main>
    );
  }

  if (query.isError && query.data === undefined) {
    return (
      <main className={PAGE_CLASS}>
        <WebnovelInfoFailure query={query} />
      </main>
    );
  }

  return (
    <main className={PAGE_CLASS}>
      <WebnovelInfoContent novel={query.data} />
    </main>
  );
}

/** 작품 정보를 못 읽었을 때 — 소장했던 사람에게는 열람 종료 이유, 없는 소설은 찾을 수 없음, 그 밖은 다시 시도. */
function WebnovelInfoFailure({ query }: { query: ReturnType<typeof useWebnovelQuery> }) {
  const failure = toWebnovelLoadFailure(query.error);
  if (failure.kind === "ended") {
    return <ReadingEndedState reason={failure.reason} refundedAmount={failure.refundedAmount} />;
  }
  if (failure.kind === "missing") {
    return (
      <NovelStatusState icon={<BookX aria-hidden className="size-8 text-muted-foreground" />} title="소설을 찾을 수 없어요">
        <p className="text-sm text-muted-foreground">지워졌거나 지금은 볼 수 없는 소설이에요.</p>
        <Button asChild variant="outline">
          <Link to="/webnovels">노벨 둘러보기</Link>
        </Button>
      </NovelStatusState>
    );
  }
  return (
    <NovelStatusState icon={<CloudOff aria-hidden className="size-8 text-muted-foreground" />} title="소설을 불러오지 못했어요">
      <p className="text-sm text-muted-foreground">잠시 후 다시 시도해주세요.</p>
      <Button
        type="button"
        variant="outline"
        aria-disabled={query.isFetching}
        className="aria-disabled:opacity-65"
        onClick={() => {
          if (query.isFetching) return;
          void query.refetch();
        }}
      >
        다시 시도
      </Button>
    </NovelStatusState>
  );
}

function WebnovelInfoContent({ novel }: { novel: WebnovelDetailResponse }) {
  const tocHeadingId = useId();
  const tocProgressId = useId();
  // 읽음 진행·이어 읽기는 내 소설과 같은 규칙이다. 노벨 목차는 화마다 읽던 자리(다 읽음 포함)로 그 표시를 준다.
  const chapters = novel.chapters.map((chapter) => ({
    ...chapter,
    finishedReading: chapter.readingPosition?.finished ?? false,
  }));
  const progress = toNovelReadProgress(chapters);
  const resume = toResumeTarget(chapters, novel.lastRead?.chapterId);
  const credit = toSourceCredit(novel.source);
  const publisher = toPublisherCredit(novel);
  const isSalesStopped = novel.salesStopped === true;
  const meta = [`${novel.chapters.length}화`, toPriceMeta(novel, isSalesStopped)].join(" · ");

  return (
    <>
      {/* 표지와 글은 모든 폭에서 가로로 놓는다 — 좁은 화면에서 표지를 위로 쌓으면 읽기 시작과 목차가 첫 화면 밖으로
          밀린다. */}
      <div className="flex items-start gap-4 sm:gap-6">
        <WebnovelCover url={novel.source.coverUrl} isPriority className="w-28 sm:w-40" />
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <h1 className="text-2xl font-bold tracking-tight text-balance break-keep text-foreground">{novel.title}</h1>
          <div className="flex flex-col gap-1 text-sm">
            <WebnovelSourceCredit source={novel.source} isLinked />
            {/* 원작자 닉네임은 글자만 — 응답에 원작자 회원 id 가 없어 프로필로 걸 수 없다. 목록 행(한 줄 잘림)에는 넣지 않는다.
                탈퇴한 사람은 이름 자리에 "탈퇴한 사용자"를 이름 잉크가 아니라 줄 잉크 그대로 쓴다 — 이름이 아니라 상태다. */}
            {credit.creator !== undefined && (
              <p className="min-w-0 break-keep text-muted-foreground">
                원작자 ·{" "}
                {credit.creator.kind === "nickname" ? (
                  <span className="text-foreground">{credit.creator.nickname}</span>
                ) : (
                  WITHDRAWN_USER_LABEL
                )}
              </p>
            )}
            {publisher !== undefined && (
              <p className="min-w-0 break-keep text-muted-foreground">
                게시자 ·{" "}
                {publisher.kind === "profile" ? (
                  <Link
                    to="/profile/$userId"
                    params={{ userId: publisher.userId }}
                    className="rounded-sm text-foreground hover:underline focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                  >
                    {publisher.nickname}
                  </Link>
                ) : (
                  WITHDRAWN_USER_LABEL
                )}
                {credit.publisherIsCreator && " · 원작자"}
              </p>
            )}
            <p className="break-keep text-muted-foreground tabular-nums">{meta}</p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {/* 노벨의 모든 작품이 AI 대화에서 나온 소설이라는 표시. 중립 상태 배지 — 색 없이 테두리와 글자로만. */}
            <span className="inline-flex w-fit items-center gap-1 rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground">
              <Sparkles aria-hidden className="size-3" />
              AI 대화로 만든 소설
            </span>
            {/* 원작자가 아닌 사람이 공개한 소설. 같은 중립 배지 꼴 — 경고가 아니라 출처 표기다. */}
            {credit.isUnofficial && (
              <span className="inline-flex w-fit items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground">
                또나 채팅 기반 파생 소설
              </span>
            )}
          </div>
        </div>
      </div>

      {isSalesStopped && (
        <p className="rounded-lg border border-border p-3 text-sm break-keep text-muted-foreground">
          지금은 판매하지 않는 소설이에요. 소장한 화와 무료 화는 계속 읽을 수 있어요.
        </p>
      )}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
        {resume !== undefined && (
          // 이 화면의 유일한 솔리드 채움.
          <Button asChild className="w-full sm:w-auto">
            <Link to="/webnovels/$novelId/episodes/$chapterId" params={{ novelId: novel.id, chapterId: resume.chapter.id }}>
              {resume.kind === "start" ? `${resume.chapter.ordinal}화부터 읽기` : `이어 읽기 · ${resume.chapter.ordinal}화`}
            </Link>
          </Button>
        )}
        {/* 좋아요는 누르는 버튼, 조회 수는 글자뿐이다. `font-normal` 은 버튼의 medium 을 옆 조회 수와 같은 본문 굵기로
            되돌린다(작품 상세의 지표 줄과 같은 꼴). */}
        <div className="flex items-center gap-2 text-sm text-muted-foreground tabular-nums">
          {!isSalesStopped && (
            <WebnovelLikeButton
              novelId={novel.id}
              liked={novel.liked}
              likeCount={novel.likeCount}
              className="h-8 px-2 text-sm font-normal text-muted-foreground pointer-coarse:h-10"
            />
          )}
          <span className="inline-flex items-center gap-1.5">
            <Eye aria-hidden className="size-4" />
            <span className="sr-only">조회</span>
            {formatCompactCount(novel.viewCount)}
          </span>
          {!isSalesStopped && <WebnovelActionsMenu novelId={novel.id} isPublisher={novel.isPublisher} />}
        </div>
      </div>

      {novel.synopsis !== "" && (
        <p className="text-sm whitespace-pre-line text-pretty break-keep text-foreground">{novel.synopsis}</p>
      )}

      <nav aria-labelledby={tocHeadingId} aria-describedby={tocProgressId} className="flex flex-col gap-3">
        <NovelReadProgressSummary
          heading={
            <h2 id={tocHeadingId} className="text-lg font-semibold text-foreground">
              목차
            </h2>
          }
          progress={progress}
          labelId={tocProgressId}
        />
        <div className="-mx-3">
          <WebnovelTocList
            novelId={novel.id}
            chapters={novel.chapters}
            lastReadChapterId={novel.lastRead?.chapterId}
            surface="page"
            isSalesStopped={isSalesStopped}
          />
        </div>
      </nav>
    </>
  );
}

/** 메타 줄의 가격 자리 — 게시자 본인은 늘 무료, 판매를 멈춘 소설은 살 수 없어 가격 대신 "판매 중지"다. */
function toPriceMeta(novel: WebnovelDetailResponse, isSalesStopped: boolean): string {
  if (novel.isPublisher) return "내가 공개한 소설이라 모든 화 무료";
  if (isSalesStopped) return "판매 중지";
  return toWebnovelPriceSummary({
    chapters: novel.chapters,
    freeChapterCount: novel.freeChapterCount,
    chapterPrice: novel.chapterPrice,
  });
}

function WebnovelInfoSkeleton() {
  return (
    <div aria-hidden className="flex flex-col gap-8">
      <div className="flex items-start gap-4 sm:gap-6">
        <div className="aspect-story w-28 shrink-0 animate-pulse rounded-xl bg-muted sm:w-40" />
        <div className="flex flex-1 flex-col gap-3">
          <div className="h-8 w-2/3 animate-pulse rounded-lg bg-muted" />
          <div className="h-5 w-1/2 animate-pulse rounded-lg bg-muted" />
          <div className="h-5 w-1/3 animate-pulse rounded-lg bg-muted" />
        </div>
      </div>
      <div className="h-9 w-full animate-pulse rounded-lg bg-muted sm:w-40" />
      <div className="flex flex-col gap-3">
        <div className="h-6 w-16 animate-pulse rounded-lg bg-muted" />
        <div className="h-12 w-full animate-pulse rounded-lg bg-muted" />
        <div className="h-12 w-full animate-pulse rounded-lg bg-muted" />
        <div className="h-12 w-full animate-pulse rounded-lg bg-muted" />
      </div>
    </div>
  );
}
