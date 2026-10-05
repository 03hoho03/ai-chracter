import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link, useNavigate } from "@tanstack/react-router";
import { BookX, CloudOff } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { CONTENT_TYPE_LABEL, ContentListEmptyState } from "@/entities/content";
import {
  NovelizeLockedState,
  toNovelLoadFailure,
  useNovelQuery,
  type NovelChapterSummary,
  type NovelDetailResponse,
} from "@/entities/novel";
import { ConfirmNovelSpendModal } from "@/features/confirm-novel-spend";
import {
  NovelChapterMaker,
  RegenerateChapterButton,
  useNovelChapterJob,
  type NovelChapterJobFlow,
} from "@/features/create-novel-chapter";

import { resolveSelectedChapter, toChapterSearchValue } from "../model/novelChapterSearch";

const PAGE_CLASS = "mx-auto flex max-w-2xl flex-col gap-8 px-4 sm:px-6 py-10";

type NovelPageProps = {
  novelId: string;
  /** 주소의 `?chapter=`. 부재면 마지막 장이다. */
  chapter: number | undefined;
};

/** `/novels/$novelId` — 소설 하나. 장 하나씩 보이고 위에 목차가 있다. 장 안은 문서 스크롤이라 사이트 푸터가
 * 그대로 있다. */
export function NovelPage({ novelId, chapter }: NovelPageProps) {
  const query = useNovelQuery(novelId);

  if (query.isPending) {
    return (
      <main className={PAGE_CLASS}>
        <NovelSkeleton />
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
      {/* 장 만들기 상태(지켜보는 작업·결과 안내)는 소설 하나에 묶인다 — 같은 라우트에서 다른 소설로 옮기면 새로
          마운트해 이전 소설의 작업을 들고 가지 않게 한다. */}
      <NovelContent key={query.data.id} novel={query.data} chapter={chapter} />
    </main>
  );
}

function NovelContent({ novel, chapter }: { novel: NovelDetailResponse; chapter: number | undefined }) {
  const navigate = useNavigate();
  // 작업이 끝나 새로 만든(다시 만든) 장. 그 장의 제목이 그려지면 포커스를 받고 비운다.
  const [focusChapterId, setFocusChapterId] = useState<string | undefined>(undefined);
  const flow = useNovelChapterJob({
    novel,
    // 금액 확인은 다른 기능의 모달이라 이 화면이 넣어 준다(기능끼리 서로 가져다 쓰지 않는다).
    confirmSpend: (props) => ConfirmNovelSpendModal.call(props),
    onChapterReady: (readyChapter, chapters) => {
      setFocusChapterId(readyChapter.id);
      void navigate({
        to: "/novels/$novelId",
        params: { novelId: novel.id },
        search: (prev) => ({ ...prev, chapter: toChapterSearchValue(chapters, readyChapter.ordinal) }),
      });
    },
  });
  const selectedChapter = resolveSelectedChapter(novel.chapters, chapter);
  const meta = [CONTENT_TYPE_LABEL[novel.contentType], novel.chapters.length > 0 ? `${novel.chapters.length}장` : undefined]
    .filter((part) => part !== undefined)
    .join(" · ");
  const isRoomGone = novel.chatRoomId === null;

  return (
    <>
      <div className="flex flex-col gap-1.5">
        <h1 className="break-keep text-2xl font-bold tracking-tight text-foreground">{novel.contentTitle}</h1>
        <p className="text-sm break-keep text-muted-foreground">
          {meta}
          {isRoomGone && " · 원래 대화방은 지워졌어요"}
        </p>
      </div>

      {selectedChapter === undefined ? (
        // 왜 만들 수 없는지(대화방이 지워짐)는 아래 만들기 버튼 바로 밑 문장이 말한다 — 여기서 되풀이하지 않는다.
        <ContentListEmptyState title="아직 장이 없어요" message="만든 장이 여기에 차례로 쌓여요." />
      ) : (
        <>
          <NovelChapterToc novelId={novel.id} chapters={novel.chapters} selectedOrdinal={selectedChapter.ordinal} />
          <NovelChapterHeading
            chapter={selectedChapter}
            flow={flow}
            shouldFocus={focusChapterId === selectedChapter.id}
            onFocused={() => setFocusChapterId(undefined)}
          />
        </>
      )}

      <NovelChapterMaker flow={flow} hasChapters={novel.chapters.length > 0} />
    </>
  );
}

/** 보고 있는 장의 머리. 작업이 끝나 새 장(다시 만든 장)으로 옮겨 오면 이 제목이 포커스를 받는다 — 무엇이 생겼는지를
 * 화면 낭독기에도 알리고, 다음 Tab 이 그 장에서 이어진다. 제목은 조작 대상이 아니라 `tabIndex=-1` 이고 포커스
 * 테두리를 그리지 않는다. */
function NovelChapterHeading({
  chapter,
  flow,
  shouldFocus,
  onFocused,
}: {
  chapter: NovelChapterSummary;
  flow: NovelChapterJobFlow;
  shouldFocus: boolean;
  onFocused: () => void;
}) {
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (!shouldFocus) return;
    headingRef.current?.focus();
    onFocused();
    // `onFocused` 는 렌더마다 새로 만들어지는 화살표라 넣지 않는다 — 포커스 시점은 `shouldFocus` 가 정한다.
  }, [shouldFocus]);

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 ref={headingRef} tabIndex={-1} className="text-lg font-semibold text-foreground outline-none">
        {chapter.ordinal}장
      </h2>
      <RegenerateChapterButton flow={flow} chapter={chapter} />
    </div>
  );
}

/** 목차. 장이 수십 개까지 늘어날 수 있어 가로로 줄바꿈하는 번호 칩이다. 고르는 것이 아니라 주소를 옮기는 링크라
 * 현재 장은 `aria-current` 로 알리고, 표시는 무채색으로만 가른다(유채색 솔리드 채움은 실행 버튼에만 쓴다) —
 * 밝기 천장인 `foreground` 테두리와 굵기로 쉬는 칩(`input` 테두리·흐린 글자)과 갈린다. */
function NovelChapterToc({
  novelId,
  chapters,
  selectedOrdinal,
}: {
  novelId: string;
  chapters: NovelChapterSummary[];
  selectedOrdinal: number;
}) {
  const headingId = useId();

  return (
    <nav aria-labelledby={headingId} className="flex flex-col gap-2">
      <h2 id={headingId} className="text-sm font-medium text-muted-foreground">
        목차
      </h2>
      <ol className="flex flex-wrap gap-2">
        {chapters.map((item) => {
          const isCurrent = item.ordinal === selectedOrdinal;
          return (
            <li key={item.id}>
              <Link
                to="/novels/$novelId"
                params={{ novelId }}
                search={(prev) => ({ ...prev, chapter: toChapterSearchValue(chapters, item.ordinal) })}
                aria-current={isCurrent ? "page" : undefined}
                className={cn(
                  "inline-flex h-8 min-w-12 items-center justify-center rounded-full border px-3 text-sm tabular-nums outline-none motion-safe:transition-colors focus-visible:ring-3 focus-visible:ring-ring/50",
                  isCurrent
                    ? "border-foreground font-semibold text-foreground"
                    : "border-input text-muted-foreground hover:bg-secondary hover:text-foreground",
                )}
              >
                {item.ordinal}장
              </Link>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function NovelStatusState({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-16 text-center break-keep">
      {icon}
      <h1 className="text-lg font-semibold text-foreground">{title}</h1>
      {children}
    </div>
  );
}

function NovelSkeleton() {
  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-1.5">
        <div className="h-8 w-2/3 animate-pulse rounded-lg bg-muted" />
        <div className="h-5 w-1/4 animate-pulse rounded-lg bg-muted" />
      </div>
      <div className="flex flex-wrap gap-2">
        <div className="h-8 w-12 animate-pulse rounded-full bg-muted" />
        <div className="h-8 w-12 animate-pulse rounded-full bg-muted" />
        <div className="h-8 w-12 animate-pulse rounded-full bg-muted" />
      </div>
    </div>
  );
}
