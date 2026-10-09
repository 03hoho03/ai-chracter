import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { BookX, ChevronLeft, CloudOff } from "lucide-react";
import type { ReactNode } from "react";

import { NovelStatusState } from "@/entities/novel";
import {
  ReadingEndedState,
  toWebnovelLoadFailure,
  useWebnovelChapterQuery,
  useWebnovelQuery,
} from "@/entities/webnovel";

import { WebnovelLockedEpisode } from "./WebnovelLockedEpisode";
import { WebnovelViewer } from "./WebnovelViewer";

/** `/webnovels/$novelId/episodes/$chapterId` — 노벨 화 하나. 작품 정보(목차·이웃 화·읽던 자리)와 화(본문 또는 잠김)를
 * 함께 받는다. 읽을 수 있으면 몰입 뷰어, 아직 소장하지 않은 유료 화면 소장 화면이다 — 사면 같은 주소에서 본문을 다시
 * 받아 뷰어로 바뀐다.
 *
 * 읽을 수 없으면 소장했던 사람에게만 이유(열람 종료)를, 나머지에게는 찾을 수 없다고만 한다. 화의 이유가 소설의
 * 이유보다 앞선다(그 화만 지워졌을 수 있다). 전역 헤더·푸터가 없는 화면이라 상태 화면에도 나가는 링크를 둔다. */
export function WebnovelEpisodePage({ novelId, chapterId }: { novelId: string; chapterId: string }) {
  const novelQuery = useWebnovelQuery(novelId);
  const chapterQuery = useWebnovelChapterQuery(novelId, chapterId);

  const chapterFailure =
    chapterQuery.isError && chapterQuery.data === undefined ? toWebnovelLoadFailure(chapterQuery.error) : undefined;
  const novelFailure =
    novelQuery.isError && novelQuery.data === undefined ? toWebnovelLoadFailure(novelQuery.error) : undefined;
  const ended = [chapterFailure, novelFailure].find((failure) => failure?.kind === "ended");

  if (ended?.kind === "ended") {
    return (
      <StatusShell novelId={undefined}>
        <ReadingEndedState reason={ended.reason} refundedAmount={ended.refundedAmount} />
      </StatusShell>
    );
  }

  if (novelFailure?.kind === "missing") {
    return (
      <StatusShell novelId={undefined}>
        <NovelStatusState icon={<BookX aria-hidden className="size-8 text-muted-foreground" />} title="소설을 찾을 수 없어요">
          <p className="text-sm text-muted-foreground">지워졌거나 지금은 볼 수 없는 소설이에요.</p>
          <Button asChild variant="outline">
            <Link to="/webnovels">노벨 둘러보기</Link>
          </Button>
        </NovelStatusState>
      </StatusShell>
    );
  }

  if (chapterFailure?.kind === "missing") {
    return (
      <StatusShell novelId={novelId}>
        <NovelStatusState icon={<BookX aria-hidden className="size-8 text-muted-foreground" />} title="이 화를 찾을 수 없어요">
          <p className="text-sm text-muted-foreground">지워졌거나 이 소설의 화가 아니에요.</p>
          <Button asChild variant="outline">
            <Link to="/webnovels/$novelId" params={{ novelId }}>
              목차 보기
            </Link>
          </Button>
        </NovelStatusState>
      </StatusShell>
    );
  }

  if (novelFailure !== undefined || chapterFailure !== undefined) {
    const isFetching = novelQuery.isFetching || chapterQuery.isFetching;
    return (
      <StatusShell novelId={novelId}>
        <NovelStatusState icon={<CloudOff aria-hidden className="size-8 text-muted-foreground" />} title="이 화를 불러오지 못했어요">
          <p className="text-sm text-muted-foreground">잠시 후 다시 시도해주세요.</p>
          <Button
            type="button"
            variant="outline"
            aria-disabled={isFetching}
            className="aria-disabled:opacity-65"
            onClick={() => {
              if (isFetching) return;
              if (novelFailure !== undefined) void novelQuery.refetch();
              if (chapterFailure !== undefined) void chapterQuery.refetch();
            }}
          >
            다시 시도
          </Button>
        </NovelStatusState>
      </StatusShell>
    );
  }

  if (novelQuery.data === undefined || chapterQuery.data === undefined) return <EpisodeSkeleton novelId={novelId} />;

  const novel = novelQuery.data;
  const chapter = chapterQuery.data;
  if (chapter.access === "locked" || chapter.paragraphs === null) {
    return <WebnovelLockedEpisode key={chapter.id} novel={novel} chapter={chapter} />;
  }

  // 목차에 없는 화는 없다(같은 공개 상태에서 읽는다). 작품 정보가 그 화보다 낡았으면(그사이 새 화가 공개됐다) 화
  // 응답만으로 읽던 자리 없이 연다.
  const summary = novel.chapters.find((item) => item.id === chapter.id) ?? {
    id: chapter.id,
    ordinal: chapter.ordinal,
    title: chapter.title,
    access: chapter.access,
    price: chapter.price,
    readingPosition: chapter.readingPosition,
  };

  // 화나 공개본 판이 바뀌면 새로 마운트한다 — 바 숨김·읽은 자리 되돌리기·저장이 화마다 처음부터 시작한다.
  return (
    <WebnovelViewer
      key={`${chapter.id}:${chapter.edition}`}
      novel={novel}
      summary={summary}
      chapter={chapter}
      paragraphs={chapter.paragraphs}
    />
  );
}

/** 상태 화면 껍데기 — 전역 헤더가 없으므로 작품 정보로 나가는 링크를 위에 둔다(소설 자체를 볼 수 없으면 없다 — 상태
 * 화면의 버튼이 출구다). */
function StatusShell({ novelId, children }: { novelId: string | undefined; children: ReactNode }) {
  return (
    <main className="mx-auto flex min-h-dvh max-w-prose flex-col gap-8 px-6 pt-10-safe pb-10">
      {novelId !== undefined && (
        <Link
          to="/webnovels/$novelId"
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

/** 로딩 — 머리 링크와 제목 자리, 문단 여섯 줄. 스켈레톤은 진행 표시라 모션 가드를 걸지 않는다. */
function EpisodeSkeleton({ novelId }: { novelId: string }) {
  return (
    <StatusShell novelId={novelId}>
      <div aria-hidden className="flex flex-col gap-4">
        <div className="h-8 w-2/3 animate-pulse rounded-lg bg-muted" />
        {["w-full", "w-11/12", "w-full", "w-4/5", "w-full", "w-2/3"].map((width, index) => (
          <div key={index} className={`h-5 ${width} animate-pulse rounded-lg bg-muted`} />
        ))}
      </div>
    </StatusShell>
  );
}
