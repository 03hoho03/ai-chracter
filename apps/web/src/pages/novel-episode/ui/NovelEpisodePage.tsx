import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { BookX, ChevronLeft, CloudOff } from "lucide-react";
import type { ReactNode } from "react";

import {
  NovelizeLockedState,
  NovelStatusState,
  toNovelLoadFailure,
  useNovelChapterQuery,
  useNovelQuery,
  type NovelChapterSummary,
  type NovelDetailResponse,
} from "@/entities/novel";
import { NovelViewer } from "@/widgets/novel-viewer";

/** `/novels/$novelId/episodes/$chapterId` — 화 하나를 읽는 몰입 화면. 화 조회 응답에는 본문만 있어 제목·요약·작가의
 * 말·읽음은 소설 상세의 목차에서 찾는다 — 두 쿼리를 함께 쓴다(상세가 알려 준 현재 개정으로 본문 캐시를 고른다).
 *
 * 전역 헤더·푸터가 없는 화면이라 로딩·실패·없음 상태에도 작품 정보로 나가는 링크를 둔다(바 없이 갇히지 않게). */
export function NovelEpisodePage({ novelId, chapterId }: { novelId: string; chapterId: string }) {
  const novelQuery = useNovelQuery(novelId);

  if (novelQuery.isPending) return <EpisodeSkeleton novelId={novelId} />;

  if (novelQuery.isError) {
    const failure = toNovelLoadFailure(novelQuery.error);
    if (failure === "locked") {
      return (
        <EpisodeStatusShell novelId={novelId}>
          <NovelizeLockedState />
        </EpisodeStatusShell>
      );
    }
    if (failure === "missing") {
      return (
        <EpisodeStatusShell novelId={novelId} hasNovel={false}>
          <NovelStatusState icon={<BookX aria-hidden className="size-8 text-muted-foreground" />} title="소설을 찾을 수 없어요">
            <p className="text-sm text-muted-foreground">지워졌거나 이 계정의 소설이 아니에요.</p>
            <Button asChild variant="outline">
              <Link to="/novels">내 소설 보기</Link>
            </Button>
          </NovelStatusState>
        </EpisodeStatusShell>
      );
    }
    if (novelQuery.data === undefined) {
      return (
        <EpisodeStatusShell novelId={novelId}>
          <RetryState
            title="소설을 불러오지 못했어요"
            isFetching={novelQuery.isFetching}
            onRetry={() => void novelQuery.refetch()}
          />
        </EpisodeStatusShell>
      );
    }
  }

  const summary = novelQuery.data.chapters.find((chapter) => chapter.id === chapterId);
  if (summary === undefined) {
    // 지워진 마지막 묶음의 화 주소, 손으로 고친 주소.
    return (
      <EpisodeStatusShell novelId={novelId}>
        <NovelStatusState icon={<BookX aria-hidden className="size-8 text-muted-foreground" />} title="이 화를 찾을 수 없어요">
          <p className="text-sm text-muted-foreground">지워졌거나 이 소설의 화가 아니에요.</p>
          <Button asChild variant="outline">
            <Link to="/novels/$novelId" params={{ novelId }}>
              목차 보기
            </Link>
          </Button>
        </NovelStatusState>
      </EpisodeStatusShell>
    );
  }

  return <EpisodeContent key={summary.id} novel={novelQuery.data} summary={summary} />;
}

/** 화 하나. 화를 옮기면 key 가 바뀌어 새로 마운트한다 — 읽기 화면의 바 숨김·읽은 자리·저장이 화마다 새로 시작한다. */
function EpisodeContent({ novel, summary }: { novel: NovelDetailResponse; summary: NovelChapterSummary }) {
  const chapterQuery = useNovelChapterQuery(novel.id, summary.id, summary.currentRevisionId);

  if (chapterQuery.isPending) return <EpisodeSkeleton novelId={novel.id} />;
  if (chapterQuery.isError && chapterQuery.data === undefined) {
    return (
      <EpisodeStatusShell novelId={novel.id}>
        <RetryState
          title="이 화를 불러오지 못했어요"
          isFetching={chapterQuery.isFetching}
          onRetry={() => void chapterQuery.refetch()}
        />
      </EpisodeStatusShell>
    );
  }

  // 본문이 바뀌면(다른 곳에서 고친 새 개정) 읽은 자리를 그 본문 기준으로 다시 잡도록 새로 마운트한다.
  return <NovelViewer key={chapterQuery.data.revision.id} novel={novel} summary={summary} chapter={chapterQuery.data} />;
}

/** 읽기 화면의 상태 화면 껍데기 — 전역 헤더가 없으므로 작품 정보로 나가는 링크를 위에 둔다. */
function EpisodeStatusShell({
  novelId,
  hasNovel = true,
  children,
}: {
  novelId: string;
  /** 소설 자체가 없으면 작품 정보로 갈 수 없다 — 그 상태의 "내 소설 보기" 버튼이 출구다. */
  hasNovel?: boolean;
  children: ReactNode;
}) {
  return (
    <main className="mx-auto flex min-h-dvh max-w-prose flex-col gap-8 px-6 pt-10-safe pb-10">
      {hasNovel && (
        <Link
          to="/novels/$novelId"
          params={{ novelId }}
          className="flex w-fit items-center gap-1 rounded-sm text-sm text-muted-foreground hover:text-foreground focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <ChevronLeft aria-hidden className="size-4" />
          작품 정보
        </Link>
      )}
      {children}
    </main>
  );
}

function RetryState({ title, isFetching, onRetry }: { title: string; isFetching: boolean; onRetry: () => void }) {
  return (
    <NovelStatusState icon={<CloudOff aria-hidden className="size-8 text-muted-foreground" />} title={title}>
      <p className="text-sm text-muted-foreground">잠시 후 다시 시도해주세요.</p>
      <Button
        type="button"
        variant="outline"
        aria-disabled={isFetching}
        className="aria-disabled:opacity-65"
        onClick={() => {
          if (isFetching) return;
          onRetry();
        }}
      >
        다시 시도
      </Button>
    </NovelStatusState>
  );
}

/** 로딩 — 머리 링크와 제목 자리, 문단 여섯 줄. 스켈레톤은 진행 표시라 모션 가드를 걸지 않는다. */
function EpisodeSkeleton({ novelId }: { novelId: string }) {
  return (
    <EpisodeStatusShell novelId={novelId}>
      <div aria-hidden className="flex flex-col gap-4">
        <div className="h-8 w-2/3 animate-pulse rounded-lg bg-muted" />
        <div className="h-4 w-16 animate-pulse rounded-lg bg-muted" />
        {["w-full", "w-11/12", "w-full", "w-4/5", "w-full", "w-2/3"].map((width, index) => (
          <div key={index} className={`h-5 ${width} animate-pulse rounded-lg bg-muted`} />
        ))}
      </div>
    </EpisodeStatusShell>
  );
}
