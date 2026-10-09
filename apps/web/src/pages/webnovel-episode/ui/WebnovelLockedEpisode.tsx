import { Button } from "@ai-character-chat/ui/components/button";
import { SheetTitle } from "@ai-character-chat/ui/components/sheet";
import { ChevronLeft, ListOrdered, Lock } from "lucide-react";
import { useRef, useState } from "react";

import { CloverIcon } from "@/entities/clover";
import { toEpisodeLabel } from "@/entities/novel";
import {
  toLockedChapterSentence,
  WebnovelTocList,
  type WebnovelChapterResponse,
  type WebnovelDetailResponse,
} from "@/entities/webnovel";
import { PurchaseWebnovelChapterModal } from "@/features/purchase-webnovel-chapter";
import { NovelInfoLink, VIEWER_BAR_ROW_PX, ViewerTocSheet } from "@/widgets/novel-viewer";

type WebnovelLockedEpisodeProps = {
  novel: WebnovelDetailResponse;
  /** 아직 소장하지 않은 유료 화(`access: "locked"` — 본문이 없고 가격만 있다). */
  chapter: WebnovelChapterResponse;
};

/** 노벨에서 아직 소장하지 않은 화의 주소로 왔을 때 판형 대신 그리는 소장 화면. 목차·화 끝 "다음 화"·아래 바·직접
 * 주소 — 모든 길이 이 화면을 지난다. 들어오자마자 확인 모달을 띄우지 않는다 — 화면이 바뀐 직후의 모달은 어두운
 * 방에서 놀람이고, 이 화면은 주소로 공유돼도 뜻이 선다.
 *
 * 위 바는 늘 보인다(뒤로·화 제목·목차) — 읽을 본문이 없어 바를 숨길 까닭이 없고, 보기 설정도 둘 자리가 없다. 화 댓글도
 * 없다(못 읽는 화의 댓글은 보이지 않는다). 솔리드는 "소장하고 읽기" 하나다. 사면 같은 주소에서 본문을 다시 받아
 * 읽기 화면으로 바뀐다.
 *
 * 소장 확인 모달은 여기 마운트한다 — 루트에 두면 노벨 코드가 첫 화면 번들로 끌려온다. 모달을 여는 곳은 이 화면뿐이다. */
export function WebnovelLockedEpisode({ novel, chapter }: WebnovelLockedEpisodeProps) {
  const [isTocOpen, setIsTocOpen] = useState(false);
  const tocOpenerRef = useRef<HTMLElement | null>(null);
  const episodeLabel = toEpisodeLabel(chapter);
  const price = chapter.price ?? novel.chapterPrice;

  function openToc(opener: HTMLElement) {
    tocOpenerRef.current = opener;
    setIsTocOpen(true);
  }

  return (
    <>
      <nav aria-label="읽기 메뉴" className="fixed inset-x-0 top-0 z-30 border-b border-border bg-background px-safe pt-safe">
        <div className="flex items-center gap-1 px-4 sm:px-6" style={{ height: VIEWER_BAR_ROW_PX }}>
          <Button asChild variant="ghost" size="icon" className="-ml-2 shrink-0">
            <NovelInfoLink route="public" novelId={novel.id} aria-label="작품 정보">
              <ChevronLeft aria-hidden />
            </NovelInfoLink>
          </Button>
          <p className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">{episodeLabel}</p>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="목차"
            className="-mr-2 shrink-0"
            onClick={(event) => openToc(event.currentTarget)}
          >
            <ListOrdered aria-hidden />
          </Button>
        </div>
      </nav>

      {/* 위 바(고정) 밑에서 시작한다 — 바 높이와 같은 px 상수 + 여백 + 노치. */}
      <main
        className="mx-auto flex min-h-dvh max-w-prose flex-col items-center justify-center gap-3 px-6 pb-10 text-center break-keep"
        style={{ paddingTop: `calc(${VIEWER_BAR_ROW_PX + 24}px + env(safe-area-inset-top))` }}
      >
        <span className="flex size-14 items-center justify-center rounded-full bg-secondary">
          <Lock aria-hidden className="size-6 text-muted-foreground" />
        </span>
        <p className="text-sm text-muted-foreground">{novel.title}</p>
        <h1 className="text-2xl font-bold tracking-tight text-balance text-foreground">{episodeLabel}</h1>
        <p className="max-w-sm text-sm text-pretty text-muted-foreground">
          {toLockedChapterSentence(novel.freeChapterCount)}
        </p>
        <div className="mt-4 flex w-full max-w-xs flex-col gap-2">
          <Button
            type="button"
            className="w-full"
            onClick={() =>
              void PurchaseWebnovelChapterModal.call({
                novelId: novel.id,
                chapterId: chapter.id,
                ordinal: chapter.ordinal,
                novelTitle: novel.title,
                episodeLabel,
                price,
                freeChapterCount: novel.freeChapterCount,
              })
            }
          >
            <CloverIcon className="size-4" />
            {price.toLocaleString()}클로버로 소장하고 읽기
          </Button>
          <div className="flex justify-center gap-2">
            <Button type="button" variant="ghost" onClick={(event) => openToc(event.currentTarget)}>
              목차
            </Button>
            <Button asChild variant="ghost">
              <NovelInfoLink route="public" novelId={novel.id}>
                작품 정보
              </NovelInfoLink>
            </Button>
          </div>
        </div>
      </main>

      <ViewerTocSheet
        open={isTocOpen}
        onOpenChange={setIsTocOpen}
        returnFocusTo={() => tocOpenerRef.current}
        heading={<SheetTitle>목차</SheetTitle>}
      >
        <WebnovelTocList
          novelId={novel.id}
          chapters={novel.chapters}
          lastReadChapterId={novel.lastRead?.chapterId}
          currentChapterId={chapter.id}
          surface="sheet"
          onNavigate={() => setIsTocOpen(false)}
        />
      </ViewerTocSheet>

      <PurchaseWebnovelChapterModal />
    </>
  );
}
