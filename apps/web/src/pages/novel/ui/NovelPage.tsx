import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useBlocker, useNavigate } from "@tanstack/react-router";
import { BookX, CloudOff } from "lucide-react";
import { useEffect, useId, useRef, useState, type MouseEvent, type ReactNode } from "react";

import { CONTENT_TYPE_LABEL, ContentListEmptyState } from "@/entities/content";
import {
  NovelizeLockedState,
  toNovelLoadFailure,
  useNovelQuery,
  type NovelChapterSummary,
  type NovelDetailResponse,
} from "@/entities/novel";
import { ConfirmChapterSpendModal, ConfirmNovelSpendModal } from "@/features/confirm-novel-spend";
import { NovelChapterMaker, useNovelChapterJob } from "@/features/create-novel-chapter";
import { DeleteLastChapterModal, removeDeletedChapterCaches } from "@/features/delete-novel";
import { DiscardManualEditModal, useNovelAiEdit } from "@/features/edit-novel-chapter";
import { NovelNotesEditor } from "@/features/edit-novel-notes";
import { NovelReader } from "@/widgets/novel-reader";

import { canRemoveDeletedChapterCaches } from "../model/deletedChapterCaches";
import { shouldConfirmDraftDiscardOnHistory } from "../model/draftHistoryBlock";
import {
  PIN_CHAPTER_NAVIGATE_OPTIONS,
  novelSearchSchema,
  resolveSelectedChapter,
  toChapterSearchValue,
  toPinnedChapterSearchValue,
} from "../model/novelChapterSearch";

const PAGE_CLASS = "mx-auto flex max-w-2xl flex-col gap-8 px-4 sm:px-6 py-10";

type NovelPageProps = {
  novelId: string;
  /** 주소의 `?chapter=`. 부재면 마지막 장이다. */
  chapter: number | undefined;
};

/** `/novels/$novelId/board` — 소설 편집 화면. 장 하나씩 보이고 위에 목차가 있으며, 화 만들기·고치기·설정 노트가
 * 여기 있다. 장 안은 문서 스크롤이라 사이트 푸터가 그대로 있다. 소설 지우기는 작품 정보 화면(`/novels/$novelId`)
 * 끝에 있다. */
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
  const queryClient = useQueryClient();
  // 지웠지만 아직 캐시를 버리지 않은 화들. 화면이 그 화를 떠난 렌더의 커밋 뒤에 버린다(아래 effect).
  const [deletedChapterIds, setDeletedChapterIds] = useState<string[]>([]);
  // 작업이 끝나 새로 만든(다시 만든) 장, 또는 마지막 장을 지운 뒤의 새 마지막 장. 그 장의 제목이 그려지면 포커스를
  // 받고 비운다.
  const [focusChapterId, setFocusChapterId] = useState<string | undefined>(undefined);
  // 보고 있는 장에서 직접 고치던 글이 시작할 때와 달라졌는가. 장을 옮기면 그 장이 새로 마운트돼 글이 사라지므로 옮기기
  // 전에 이 값을 본다. 작업이 끝난 뒤의 비동기 콜백에서도 읽어야 해서 렌더 값이 아니라 ref 다.
  const isDraftDirtyRef = useRef(false);
  // 고치던 글이 있어 옮겨 가지 않고 미뤄 둔 새 장. 그 장으로 가는 링크를 목차 아래에 둔다.
  const [heldChapterId, setHeldChapterId] = useState<string | undefined>(undefined);
  // 떠 있는 "고치던 글 버리기" 확인의 수. 뒤로가 떠 있는 확인을 닫고 새로 열 때 쓴다(아래 차단 함수).
  const openDiscardConfirmCountRef = useRef(0);
  // 금액 확인은 다른 기능의 모달이라 이 화면이 넣어 준다(기능끼리 서로 가져다 쓰지 않는다). 장 다시 만들기는 모델도
  // 고르는 확인을, AI 수정은 금액만 묻는 확인을 받는다 — AI 수정은 모델을 고르지 않는다.
  const confirmSpend = (props: Parameters<typeof ConfirmNovelSpendModal.call>[0]) => ConfirmNovelSpendModal.call(props);
  const confirmChapterSpend = (props: Parameters<typeof ConfirmChapterSpendModal.call>[0]) =>
    ConfirmChapterSpendModal.call(props);
  // 이 화면이 아직 떠 있나. 장 이동 확인·마지막 장 지우기는 기다린 뒤 화면을 옮기는데, 그사이 이용자가 다른 화면으로
  // 갔으면 소설 화면으로 끌고 오지 않는다.
  const isMountedRef = useRef(false);
  // 모달은 루트에 마운트돼 라우트가 바뀌어도 남는다 — 이 화면을 떠나면(다른 소설로 옮겨 다시 마운트될 때도) 이 화면이
  // 연 모달을 닫는다. 남겨 두면 다른 화면 위에서 눌러도 아무 일 없는 버튼이 되거나, 확정하면 떠난 화면으로 끌고 온다.
  // 금액 확인은 두 흐름에 넣어 준 것이라 여기서 닫는다(두 흐름은 떠난 뒤 받은 확정으로 요청하지 않는다). 판 이력은
  // 장마다 여는 자리가 닫는다.
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      ConfirmNovelSpendModal.end(false);
      ConfirmChapterSpendModal.end(null);
      DiscardManualEditModal.end(false);
      DeleteLastChapterModal.end(false);
    };
  }, []);
  const flow = useNovelChapterJob({
    novel,
    confirmSpend: confirmChapterSpend,
    onChapterReady: (readyChapter, chapters, isRegenerated) => {
      // 다시 만든 장은 본문이 통째로 바뀌어, 장 머리에 남은 지난 고치기 결과(적용·버리기·저장)는 이제 옛 글의
      // 이야기다. 본문을 바꾸는 다른 동작이 시작할 때처럼 그 문장을 지운다. 문장이 다른 장의 "수정안이 왔어요"였어도
      // 지워지지만, 그 수정안은 그 장 본문 아래 상자로 남는다. 새 장을 만든 것은 있던 장의 본문을 바꾸지 않아 그대로
      // 둔다.
      if (isRegenerated) aiEdit.report({ type: "started" });
      // 고치던 글이 있으면 끌고 가지 않는다 — 옮기면 쓰던 글이 사라지고, 같은 장이어도 제목으로 포커스를 빼앗는다. 만든
      // 장은 링크로 알리고 옮길지는 이용자가 정한다. 진행 중 작업 동안 고치기를 잠그는 길도 있지만, 장을 옮기기 전의
      // 확인에 어차피 이 값이 필요해 여기서 하나 더 읽는 쪽이 더 단순하다(잠그면 이미 열려 있던 입력칸도 따로 다뤄야 한다).
      if (isDraftDirtyRef.current) {
        setHeldChapterId(readyChapter.id);
        return;
      }
      setFocusChapterId(readyChapter.id);
      void navigate({
        to: "/novels/$novelId/board",
        params: { novelId: novel.id },
        search: (prev) => ({ ...prev, chapter: toChapterSearchValue(chapters, readyChapter.ordinal) }),
      });
    },
  });
  const aiEdit = useNovelAiEdit({
    novel,
    confirmSpend,
    isChapterJobBusy: flow.isJobRunning || flow.preparing !== undefined,
  });
  const selectedChapter = resolveSelectedChapter(novel.chapters, chapter);
  // 지운 화의 본문·판 캐시는 그 화를 그리던 읽기 화면이 내려간 뒤에 버린다 — effect 는 커밋 뒤에 돌아 그때는 옛 화면의
  // 쿼리 구독이 이미 풀려 있다. 그 전에 버리면 남은 구독이 곧바로 다시 받아 404 가 난다.
  useEffect(() => {
    if (!canRemoveDeletedChapterCaches(deletedChapterIds, selectedChapter?.id)) return;
    removeDeletedChapterCaches(queryClient, novel.id, deletedChapterIds);
    setDeletedChapterIds([]);
  }, [deletedChapterIds, selectedChapter?.id]);
  const meta = [CONTENT_TYPE_LABEL[novel.contentType], novel.chapters.length > 0 ? `${novel.chapters.length}화` : undefined]
    .filter((part) => part !== undefined)
    .join(" · ");
  const isRoomGone = novel.chatRoomId === null;
  // 브라우저 뒤로가 같은 소설의 다른 장으로 가면 고치던 장이 새로 그려져 쓰던 글이 사라진다 — 목차·새 장 링크와
  // 같은 확인을 받는다. 그 링크에서 연 확인이 떠 있으면 먼저 닫는다: 가려던 장이 바뀌었고, 남겨 두면 옮긴 뒤에도
  // 옛 장 이름으로 묻는 모달이 화면 위에 남는다(이 화면은 그대로 마운트돼 있어 떠날 때의 정리가 돌지 않는다).
  // 새로고침·창 닫기 확인(`beforeunload`)은 이 화면이 하던 일이 아니라 켜지 않는다.
  useBlocker({
    shouldBlockFn: async ({ action, current, next }) => {
      const shouldConfirm = shouldConfirmDraftDiscardOnHistory({
        action,
        currentPathname: current.pathname,
        nextPathname: next.pathname,
        isDraftDirty: isDraftDirtyRef.current,
      });
      if (!shouldConfirm) return false;
      const target = resolveSelectedChapter(novel.chapters, novelSearchSchema.parse(next.search).chapter);
      // 같은 장이면 다시 그려지지 않아 글이 남는다.
      if (target === undefined || target.id === selectedChapter?.id) return false;
      // 떠 있던 확인을 닫고 바로 새로 열면, 새 확인이 닫힌 뒤 돌아갈 자리로 잡는 것이 곧 사라질 옛 확인의 버튼이라
      // 포커스가 문서 처음으로 떨어진다. 그때는 머무는 장의 제목으로 돌린다 — 키보드 사용자가 고치던 글 바로 위에서
      // 다시 이어 간다. 떠 있던 확인이 없으면 확인을 연 자리(입력칸)로 돌아가므로 손대지 않는다.
      const isReplacingConfirm = openDiscardConfirmCountRef.current > 0;
      DiscardManualEditModal.end(false);
      const isDiscarded = await confirmDiscard(target);
      if (isDiscarded) setFocusChapterId(target.id);
      else if (isReplacingConfirm) setFocusChapterId(selectedChapter?.id);
      return !isDiscarded;
    },
    enableBeforeUnload: false,
  });
  const heldChapter =
    heldChapterId !== undefined && heldChapterId !== selectedChapter?.id
      ? novel.chapters.find((item) => item.id === heldChapterId)
      : undefined;

  async function confirmDiscard(target: NovelChapterSummary) {
    openDiscardConfirmCountRef.current += 1;
    try {
      return await DiscardManualEditModal.call({ chapterOrdinal: target.ordinal });
    } finally {
      openDiscardConfirmCountRef.current -= 1;
    }
  }

  /** 다른 장으로 옮긴다. 고치던 글이 있으면 버릴지 먼저 묻고, 버리고 옮기면 새 장 제목으로 포커스를 옮긴다 — 장이
   * 다 만들어져 옮겨 올 때와 같은 자리다. 확인을 연 자리로 돌려보내면, 새 장 링크는 옮기면서 사라져 포커스가 문서
   * 처음으로 떨어진다. */
  async function goToChapter(target: NovelChapterSummary) {
    const isDraftDirty = isDraftDirtyRef.current;
    if (isDraftDirty && !(await confirmDiscard(target))) return;
    if (!isMountedRef.current) return;
    if (isDraftDirty) setFocusChapterId(target.id);
    setHeldChapterId(undefined);
    void navigate({
      to: "/novels/$novelId/board",
      params: { novelId: novel.id },
      search: (prev) => ({ ...prev, chapter: toChapterSearchValue(novel.chapters, target.ordinal) }),
    });
  }

  /** 장으로 가는 링크의 클릭. 고치던 글이 있을 때만 링크 이동을 멈추고 확인을 거친다. 새 탭으로 여는 클릭은 이 화면을
   * 떠나지 않으니 그대로 둔다. */
  function handleChapterLinkClick(event: MouseEvent<HTMLAnchorElement>, target: NovelChapterSummary) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (!isDraftDirtyRef.current) {
      setHeldChapterId(undefined);
      return;
    }
    event.preventDefault();
    void goToChapter(target);
  }

  function handleChapterDeleted(firstDeletedOrdinal: number, deleted: string[]) {
    if (!isMountedRef.current) {
      // 화면을 이미 떠났으면 지운 화를 보는 구독도 없다 — 바로 버린다.
      removeDeletedChapterCaches(queryClient, novel.id, deleted);
      return;
    }
    setDeletedChapterIds(deleted);
    // 지운 화들 중 첫 화 바로 앞 화가 새 마지막 화다. 주소의 화 번호를 걷어 기본값(마지막 화)으로 돌린다.
    const previous = novel.chapters.find((item) => item.ordinal === firstDeletedOrdinal - 1);
    setFocusChapterId(previous?.id);
    void navigate({
      to: "/novels/$novelId/board",
      params: { novelId: novel.id },
      search: (prev) => ({ ...prev, chapter: undefined }),
    });
  }

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
        <ContentListEmptyState title="아직 화가 없어요" message="만든 화가 여기에 차례로 쌓여요." />
      ) : (
        <>
          <NovelChapterToc
            novelId={novel.id}
            chapters={novel.chapters}
            selectedOrdinal={selectedChapter.ordinal}
            onChapterLinkClick={handleChapterLinkClick}
          />
          {heldChapter !== undefined && (
            <p className="text-sm break-keep text-muted-foreground">
              {heldChapter.ordinal}화가 생겼어요.{" "}
              <Link
                to="/novels/$novelId/board"
                params={{ novelId: novel.id }}
                search={(prev) => ({ ...prev, chapter: toChapterSearchValue(novel.chapters, heldChapter.ordinal) })}
                className="font-medium text-foreground underline underline-offset-4 outline-none focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-ring"
                onClick={(event) => handleChapterLinkClick(event, heldChapter)}
              >
                보러 가기
              </Link>
            </p>
          )}
          {/* 고치기 모드·고른 문단은 그 장에만 속한다 — 장을 옮기면 새로 마운트한다. */}
          <NovelReader
            key={selectedChapter.id}
            novel={novel}
            chapter={selectedChapter}
            chapterFlow={flow}
            aiEdit={aiEdit}
            shouldFocusHeading={focusChapterId === selectedChapter.id}
            onHeadingFocused={() => setFocusChapterId(undefined)}
            onChapterDeleted={handleChapterDeleted}
            onDraftDirtyChange={(isDirty) => {
              isDraftDirtyRef.current = isDirty;
              // 주소에 장 번호가 없으면 보이는 장은 "마지막 장"이라, 고치는 사이 새 장이 생기면 이동 없이 장이 바뀌어
              // 쓰던 글이 사라진다. 글이 생긴 순간 지금 장 번호를 주소에 박는다. 화면 안에 따로 "고정한 장" 값을 두는
              // 길도 있지만, 그러면 장을 고르는 출처가 주소와 그 값 둘이 되어 장으로 옮기는 길(목차·새 장 링크·장
              // 지우기)마다 그 값을 풀어야 한다. 주소에 박으면 장 번호가 있는 화면의 보호(이동 보류·새 장 링크·버리기
              // 확인)를 그대로 쓴다. 기록·스크롤을 건드리지 않는 까닭은 옵션 상수에 있다.
              const pinned = toPinnedChapterSearchValue({
                requested: chapter,
                selectedOrdinal: selectedChapter.ordinal,
                isDraftDirty: isDirty,
              });
              if (pinned === undefined) return;
              void navigate({
                to: "/novels/$novelId/board",
                params: { novelId: novel.id },
                search: (prev) => ({ ...prev, chapter: pinned }),
                ...PIN_CHAPTER_NAVIGATE_OPTIONS,
              });
            }}
          />
        </>
      )}

      <NovelChapterMaker flow={flow} hasChapters={novel.chapters.length > 0} />

      <NovelNotesEditor novel={novel} />
    </>
  );
}

/** 목차. 장이 수십 개까지 늘어날 수 있어 가로로 줄바꿈하는 번호 칩이다. 고르는 것이 아니라 주소를 옮기는 링크라
 * 현재 장은 `aria-current` 로 알리고, 표시는 무채색으로만 가른다(유채색 솔리드 채움은 실행 버튼에만 쓴다) —
 * 밝기 천장인 `foreground` 테두리와 굵기로 쉬는 칩(`input` 테두리·흐린 글자)과 갈린다. */
function NovelChapterToc({
  novelId,
  chapters,
  selectedOrdinal,
  onChapterLinkClick,
}: {
  novelId: string;
  chapters: NovelChapterSummary[];
  selectedOrdinal: number;
  /** 링크를 누른 순간. 고치던 글이 있으면 호출부가 이동을 멈추고 확인을 거친다. */
  onChapterLinkClick: (event: MouseEvent<HTMLAnchorElement>, chapter: NovelChapterSummary) => void;
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
                to="/novels/$novelId/board"
                params={{ novelId }}
                search={(prev) => ({ ...prev, chapter: toChapterSearchValue(chapters, item.ordinal) })}
                aria-current={isCurrent ? "page" : undefined}
                onClick={(event) => {
                  // 지금 장 링크는 다시 마운트하지 않아 쓰던 글이 그대로다 — 확인할 것이 없다.
                  if (!isCurrent) onChapterLinkClick(event, item);
                }}
                className={cn(
                  "inline-flex h-8 min-w-12 items-center justify-center rounded-full border px-3 text-sm tabular-nums outline-none motion-safe:transition-colors focus-visible:ring-3 focus-visible:ring-ring/50",
                  isCurrent
                    ? "border-foreground font-semibold text-foreground"
                    : "border-input text-muted-foreground hover:bg-secondary hover:text-foreground",
                )}
              >
                {item.ordinal}화
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
