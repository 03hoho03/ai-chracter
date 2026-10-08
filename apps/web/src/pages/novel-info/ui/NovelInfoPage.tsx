import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { BookOpen, BookX, CloudOff, Loader2, Pencil } from "lucide-react";
import { useId } from "react";

import { ContentListEmptyState } from "@/entities/content";
import {
  EpisodeTocList,
  NovelizeLockedState,
  NovelReadProgressSummary,
  NovelStatusState,
  toNovelLoadFailure,
  toNovelReadProgress,
  toResumeTarget,
  useNovelQuery,
  type NovelDetailResponse,
} from "@/entities/novel";
import { NovelCoverActions, NovelSynopsisEditor, NovelTitleEditor } from "@/features/edit-novel-info";
import { GeneratedImagePickerModal } from "@/features/select-generated-image";

import { NovelDeleteSection } from "./NovelDeleteSection";
import { NovelSourceCredit } from "./NovelSourceCredit";

const PAGE_CLASS = "mx-auto flex max-w-2xl flex-col gap-8 px-4 sm:px-6 py-10";

/** `/novels/$novelId` — 작품 정보. 소설에 들어오는 첫 화면이다: 표지·제목·원작·소개·목차와 이어 읽기. 화 본문은 화
 * 읽기 화면이, 화 만들기·고치기는 편집 화면이 맡는다. 평범한 문서 스크롤 화면이라 전역 헤더와 사이트 푸터가 있다. */
export function NovelInfoPage({ novelId }: { novelId: string }) {
  const query = useNovelQuery(novelId);

  if (query.isPending) {
    return (
      <main className={PAGE_CLASS}>
        <NovelInfoSkeleton />
      </main>
    );
  }

  // 잠김·없음은 이미 받은 상세가 있어도 이긴다 — 포커스 복귀 재조회가 "허용 회수"나 "다른 탭에서 지움"을 알려 온
  // 것이라 옛 상세를 계속 보여 줄 이유가 없다. 일시적 실패만 받은 상세를 그대로 둔다.
  if (query.isError) {
    const failure = toNovelLoadFailure(query.error);
    if (failure === "locked") {
      return (
        <main className={PAGE_CLASS}>
          <NovelizeLockedState />
        </main>
      );
    }
    if (failure === "missing") {
      return (
        <main className={PAGE_CLASS}>
          <NovelStatusState icon={<BookX aria-hidden className="size-8 text-muted-foreground" />} title="소설을 찾을 수 없어요">
            <p className="text-sm text-muted-foreground">지워졌거나 이 계정의 소설이 아니에요.</p>
            <Button asChild variant="outline">
              <Link to="/novels">내 소설 보기</Link>
            </Button>
          </NovelStatusState>
        </main>
      );
    }
    if (query.data === undefined) {
      return (
        <main className={PAGE_CLASS}>
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
        </main>
      );
    }
  }

  return (
    <main className={PAGE_CLASS}>
      {/* 고치던 제목·소개 입력은 소설 하나에 묶인다 — 같은 라우트에서 다른 소설로 옮기면 새로 마운트한다. */}
      <NovelInfoContent key={query.data.id} novel={query.data} />
    </main>
  );
}

function NovelInfoContent({ novel }: { novel: NovelDetailResponse }) {
  const tocHeadingId = useId();
  const tocProgressId = useId();
  const progress = toNovelReadProgress(novel.chapters);
  const resume = toResumeTarget(novel.chapters, novel.lastRead?.chapterId);
  const meta = [
    `${novel.chapters.length}화`,
    progress.lastFinishedOrdinal === undefined ? undefined : `${progress.lastFinishedOrdinal}화까지 읽음`,
  ]
    .filter((part) => part !== undefined)
    .join(" · ");

  return (
    <>
      {/* 표지와 글은 모든 폭에서 가로로 놓는다 — 좁은 화면에서 표지를 위로 쌓으면 이어 읽기와 목차가 첫 화면 밖으로
          밀린다. */}
      <div className="flex items-start gap-4 sm:gap-6">
        <div className="aspect-story w-28 shrink-0 overflow-hidden rounded-xl border border-foreground/10 bg-secondary sm:w-40">
          {novel.cover.url === null ? (
            <div className="flex size-full items-center justify-center">
              <BookOpen aria-hidden className="size-8 text-muted-foreground" />
            </div>
          ) : (
            // 표지는 제목 바로 옆이라 그림이 따로 말할 것이 없다.
            <img src={novel.cover.url} alt="" decoding="async" className="size-full object-cover" />
          )}
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <NovelTitleEditor novel={novel} />
          <div className="flex flex-col gap-1">
            <NovelSourceCredit novel={novel} />
            <p className="text-sm text-muted-foreground tabular-nums">{meta}</p>
          </div>
          <div className="-ml-3">
            <NovelCoverActions
              novel={novel}
              pickImage={async (currentAssetId) =>
                (
                  await GeneratedImagePickerModal.call({
                    title: "표지로 쓸 이미지 고르기",
                    description: "생성해 둔 이미지 중 하나를 이 소설의 표지로 써요.",
                    emptyHint: "이미지를 생성한 뒤 다시 열어보면 여기에 나타나요.",
                    currentAssetId,
                  })
                )?.assetId
              }
            />
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-3">
        {resume === undefined ? (
          <ContentListEmptyState
            title="아직 화가 없어요"
            message="편집 화면에서 대화를 화로 묶으면 여기에 차례로 쌓여요."
            action={
              <Button asChild>
                <Link to="/novels/$novelId/board" params={{ novelId: novel.id }}>
                  편집에서 첫 화 만들기
                </Link>
              </Button>
            }
          />
        ) : (
          <div className="flex flex-col gap-2 sm:flex-row">
            {/* 이 화면의 유일한 솔리드 채움. */}
            <Button asChild className="w-full sm:w-auto">
              <Link to="/novels/$novelId/episodes/$chapterId" params={{ novelId: novel.id, chapterId: resume.chapter.id }}>
                {resume.kind === "start" ? `${resume.chapter.ordinal}화부터 읽기` : `이어 읽기 · ${resume.chapter.ordinal}화`}
              </Link>
            </Button>
            <Button asChild variant="outline" className="w-full sm:w-auto">
              <Link to="/novels/$novelId/board" params={{ novelId: novel.id }}>
                <Pencil aria-hidden />
                편집
              </Link>
            </Button>
          </div>
        )}
        {novel.activeJob !== null && <ActiveJobNotice novelId={novel.id} />}
      </div>

      <NovelSynopsisEditor novel={novel} />

      {novel.chapters.length > 0 && (
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
            <EpisodeTocList
              novelId={novel.id}
              chapters={novel.chapters}
              lastReadChapterId={novel.lastRead?.chapterId}
              surface="page"
            />
          </div>
        </nav>
      )}

      <NovelDeleteSection novel={novel} />
    </>
  );
}

/** 진행 중인 화 만들기. 진행은 편집 화면이 지켜보고 이 화면은 알리기만 한다(여기서 묻지 않는다). 스피너는 진행 표시라
 * 모션 가드를 걸지 않는다. */
function ActiveJobNotice({ novelId }: { novelId: string }) {
  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm break-keep text-muted-foreground">
      <Loader2 aria-hidden className="size-4 animate-spin" />
      다음 화를 만들고 있어요.
      <Link
        to="/novels/$novelId/board"
        params={{ novelId }}
        className="font-medium text-foreground underline underline-offset-4 outline-none focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-ring"
      >
        편집에서 보기
      </Link>
    </p>
  );
}

function NovelInfoSkeleton() {
  return (
    <div className="flex flex-col gap-8">
      <div className="flex items-start gap-4 sm:gap-6">
        <div className="aspect-story w-28 shrink-0 animate-pulse rounded-xl bg-muted sm:w-40" />
        <div className="flex flex-1 flex-col gap-3">
          <div className="h-8 w-2/3 animate-pulse rounded-lg bg-muted" />
          <div className="h-5 w-1/2 animate-pulse rounded-lg bg-muted" />
          <div className="h-5 w-1/4 animate-pulse rounded-lg bg-muted" />
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
