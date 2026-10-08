import { Button } from "@ai-character-chat/ui/components/button";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useBlocker, useNavigate } from "@tanstack/react-router";
import { BookX, CloudOff, NotebookPen } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";

import {
  NovelStatusState,
  NovelizeLockedState,
  toNovelLoadFailure,
  useNovelBoardLayoutQuery,
  useNovelCharactersQuery,
  useNovelQuery,
  type NovelChapterSummary,
  type NovelDetailResponse,
} from "@/entities/novel";
import { ConfirmChapterSpendModal, ConfirmNovelSpendModal } from "@/features/confirm-novel-spend";
import { useNovelChapterJob } from "@/features/create-novel-chapter";
import { DeleteLastChapterModal, removeDeletedChapterCaches } from "@/features/delete-novel";
import { DiscardManualEditModal, useNovelAiEdit } from "@/features/edit-novel-chapter";
import { MergeCharacterModal } from "@/features/edit-novel-character";
import {
  DeleteSnapshotModal,
  RestoreSnapshotModal,
  SaveSnapshotModal,
  SnapshotDiffModal,
} from "@/features/novel-snapshots";
import {
  LazyNovelBoardCanvas,
  NovelBoardCanvasSkeleton,
  NovelBoardJobLine,
  NovelBoardPanel,
  NovelBoardTopBar,
  NovelFlowList,
  canSaveBoardLayout,
  hasChapterBlockedReason,
  nodeKeyToSelection,
  parseBoardSelection,
  resolveBoardSelection,
  toBoardModel,
  toBoardSelectValue,
  toSelectedNodeKey,
  useIsNovelBoardCanvasLayout,
  type BoardSelection,
} from "@/widgets/novel-board";

import { novelBoardSearchSchema } from "../model/boardSearch";
import { canRemoveDeletedChapterCaches } from "../model/deletedChapterCaches";
import { shouldConfirmDraftDiscardOnHistory } from "../model/draftHistoryBlock";

type NovelBoardPageProps = {
  novelId: string;
  /** 주소의 `?select=`. 부재면 고른 것 없음(넓은 화면은 소설 개요, 좁은 화면은 목록)이다. */
  select: string | undefined;
};

/** 고른 것이 바뀐 뒤 포커스를 둘 자리. 주소가 그 값으로 바뀐 렌더의 커밋 뒤에 옮긴다(`select` 가 맞을 때만) — 주소
 * 이동은 비동기라 고르는 순간에는 새 패널이 아직 없다. */
type PendingFocus =
  /** 새 패널의 제목. */
  | { kind: "heading"; select: string | undefined }
  /** 고르기를 푼 뒤 그 카드(넓은 화면)·목록 행(좁은 화면)·버전 토글. */
  | { kind: "origin"; select: undefined; key: string };

/**
 * `/novels/$novelId/board` — 소설 편집 보드. 전역 헤더 대신 전용 상단 바를 쓰는 뷰포트 고정 화면이다(사이트 푸터
 * 없음).
 *
 * - lg(1024px) 이상: 캔버스(화 카드 세로 한 열 + 인물 레인 + 설정 노트) + 오른쪽 패널(고른 것을 고치는 자리, 늘 있음).
 * - lg 미만: 캔버스를 마운트하지 않고 세로 흐름 목록(화·인물·설정 탭). 고르면 목록 자리가 패널 화면으로 바뀌고, 맨 위
 *   "목록"이나 기기의 뒤로 가기로 돌아간다.
 *
 * 고른 것은 주소의 `?select=` 가 정하고 기록에 쌓는다 — 새로고침·링크가 같은 패널을 열고, 휴대폰 뒤로 가기가
 * "목록으로"가 된다. 소설 지우기는 작품 정보 화면에만 있다.
 */
export function NovelBoardPage({ novelId, select }: NovelBoardPageProps) {
  const query = useNovelQuery(novelId);

  if (query.isPending) {
    return (
      <>
        <NovelBoardTopBar novelId={novelId} title={undefined} />
        <BoardLoading />
      </>
    );
  }

  // 잠김·없음은 이미 받은 상세가 있어도 이긴다 — 포커스 복귀 재조회가 "허용 회수"나 "다른 탭에서 지움"을 알려 온
  // 것이라 옛 상세를 계속 보여 줄 이유가 없다. 일시적 실패만 받은 상세를 그대로 둔다.
  if (query.isError) {
    const failure = toNovelLoadFailure(query.error);
    if (failure === "locked") {
      return (
        <BoardStatusShell novelId={novelId}>
          <NovelizeLockedState />
        </BoardStatusShell>
      );
    }
    if (failure === "missing") {
      return (
        <BoardStatusShell novelId={novelId}>
          <NovelStatusState icon={<BookX aria-hidden className="size-8 text-muted-foreground" />} title="소설을 찾을 수 없어요">
            <p className="text-sm text-muted-foreground">지워졌거나 이 계정의 소설이 아니에요.</p>
            <Button asChild variant="outline">
              <Link to="/novels">내 소설 보기</Link>
            </Button>
          </NovelStatusState>
        </BoardStatusShell>
      );
    }
    if (query.data === undefined) {
      return (
        <BoardStatusShell novelId={novelId}>
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
        </BoardStatusShell>
      );
    }
  }

  // 화 만들기 상태(지켜보는 작업·결과 안내)는 소설 하나에 묶인다 — 같은 라우트에서 다른 소설로 옮기면 새로 마운트해
  // 이전 소설의 작업을 들고 가지 않게 한다.
  return <BoardContent key={query.data.id} novel={query.data} select={select} />;
}

function BoardContent({ novel, select }: { novel: NovelDetailResponse; select: string | undefined }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isCanvasLayout = useIsNovelBoardCanvasLayout();
  const charactersQuery = useNovelCharactersQuery(novel.id);
  const layoutQuery = useNovelBoardLayoutQuery(novel.id);
  const blockedReasonId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const createButtonRef = useRef<HTMLButtonElement>(null);
  // 지웠지만 아직 캐시를 버리지 않은 화들. 화면이 그 화를 떠난 렌더의 커밋 뒤에 버린다(아래 effect).
  const [deletedChapterIds, setDeletedChapterIds] = useState<string[]>([]);
  // 고치던 글이 있어 옮겨 가지 않고 미뤄 둔 새 화. 그 화로 가는 링크를 작업 줄에 둔다.
  const [heldChapterId, setHeldChapterId] = useState<string | undefined>(undefined);
  const [pendingFocus, setPendingFocus] = useState<PendingFocus | undefined>(undefined);
  // 지금 패널에 저장하지 않은 입력이 있는가 — 화 본문 직접 고치기, 설정 노트, 인물 메모가 보고한다(패널은 한 번에
  // 하나라 칸 하나로 족하다). 다른 것을 고르면 그 패널이 새로 마운트돼 입력이 사라지므로 옮기기 전에 이 값을 본다. 작업이 끝난 뒤의 비동기 콜백에서도 읽어야 해서 렌더 값이 아니라 ref 다.
  const isDraftDirtyRef = useRef(false);
  // 떠 있는 "고치던 글 버리기" 확인의 수. 뒤로가 떠 있는 확인을 닫고 새로 열 때 쓴다(아래 차단 함수).
  const openDiscardConfirmCountRef = useRef(0);
  // 이 화면이 아직 떠 있나. 확인을 기다린 뒤 주소를 옮기는데, 그사이 이용자가 다른 화면으로 갔으면 보드로 끌고 오지
  // 않는다.
  const isMountedRef = useRef(false);

  // 모달은 이 화면을 떠나도 남을 수 있다(루트 마운트이거나 기다리던 약속이 남는다) — 떠나면(다른 소설로 옮겨 다시
  // 마운트될 때도) 이 화면이 연 모달을 닫는다. 남겨 두면 다른 화면 위에서 눌러도 아무 일 없는 버튼이 되거나, 확정하면
  // 떠난 화면으로 끌고 온다. 금액 확인은 두 흐름에 넣어 준 것이라 여기서 닫는다(두 흐름은 떠난 뒤 받은 확정으로 요청하지
  // 않는다). 판 이력은 화 패널이 닫는다. 버전·인물 합치기 모달은 이 화면에만 마운트된다(아래).
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      ConfirmNovelSpendModal.end(false);
      ConfirmChapterSpendModal.end(null);
      DiscardManualEditModal.end(false);
      DeleteLastChapterModal.end(false);
      SaveSnapshotModal.end(null);
      RestoreSnapshotModal.end(null);
      DeleteSnapshotModal.end(false);
      SnapshotDiffModal.end();
      MergeCharacterModal.end(null);
    };
  }, []);

  const selection = resolveBoardSelection(
    parseBoardSelection(select),
    novel.chapters.map((chapter) => chapter.id),
    charactersQuery.data?.map((character) => character.id),
  );
  const selectValue = selection === undefined ? undefined : toBoardSelectValue(selection);
  // 작업이 끝난 뒤의 비동기 콜백은 그 작업을 시작한 렌더의 값을 들고 있다 — 그사이 고른 것이 바뀌었을 수 있어 지금
  // 값을 ref 로 읽는다.
  const selectionRef = useRef(selection);
  selectionRef.current = selection;
  const model = useMemo(() => toBoardModel(novel, charactersQuery.data), [novel, charactersQuery.data]);

  // 금액 확인은 다른 기능의 모달이라 이 화면이 넣어 준다(기능끼리 서로 가져다 쓰지 않는다). 다시 만들기는 모델도 고르는
  // 확인을, AI 수정은 금액만 묻는 확인을 받는다 — AI 수정은 모델을 고르지 않는다.
  const confirmSpend = (props: Parameters<typeof ConfirmNovelSpendModal.call>[0]) => ConfirmNovelSpendModal.call(props);
  const confirmChapterSpend = (props: Parameters<typeof ConfirmChapterSpendModal.call>[0]) =>
    ConfirmChapterSpendModal.call(props);
  const flow = useNovelChapterJob({
    novel,
    confirmSpend: confirmChapterSpend,
    onChapterReady: (readyChapter, _chapters, isRegenerated) => {
      // 다시 만든 화는 본문이 통째로 바뀌어, 화 머리에 남은 지난 고치기 결과는 이제 옛 글의 이야기다. 본문을 바꾸는
      // 다른 동작이 시작할 때처럼 그 문장을 지운다. 새 화를 만든 것은 있던 화의 본문을 바꾸지 않아 그대로 둔다.
      if (isRegenerated) aiEdit.report({ type: "started" });
      // 그 화로 끌고 가는 것은 고른 것이 없거나 화를 보고 있고 저장하지 않은 입력이 없을 때뿐이다. 입력이 있으면
      // 옮기면 사라지고, 인물·노트·버전 패널을 보던 이용자를 화로 끌고 가지도 않는다(인물 이름·별칭처럼 보고하지
      // 않는 입력칸도 있다) — 그때는 작업 줄의 링크로 알리고 옮길지는 이용자가 정한다.
      const current = selectionRef.current;
      const isOnEpisodeOrNothing = current === undefined || current.kind === "episode";
      if (isDraftDirtyRef.current || !isOnEpisodeOrNothing) {
        setHeldChapterId(readyChapter.id);
        return;
      }
      moveTo({ kind: "episode", id: readyChapter.id });
    },
  });
  const aiEdit = useNovelAiEdit({
    novel,
    confirmSpend,
    isChapterJobBusy: flow.isJobRunning || flow.preparing !== undefined,
  });

  // 지운 화의 본문·판 캐시는 그 화를 그리던 패널이 내려간 뒤에 버린다 — effect 는 커밋 뒤에 돌아 그때는 옛 패널의
  // 쿼리 구독이 이미 풀려 있다. 그 전에 버리면 남은 구독이 곧바로 다시 받아 404 가 난다.
  const shownChapterId = selection?.kind === "episode" ? selection.id : undefined;
  useEffect(() => {
    if (!canRemoveDeletedChapterCaches(deletedChapterIds, shownChapterId)) return;
    removeDeletedChapterCaches(queryClient, novel.id, deletedChapterIds);
    setDeletedChapterIds([]);
  }, [deletedChapterIds, shownChapterId]);

  // 고른 것이 바뀐 렌더의 커밋 뒤에 포커스를 옮긴다.
  useEffect(() => {
    if (pendingFocus === undefined || pendingFocus.select !== selectValue) return;
    setPendingFocus(undefined);
    if (pendingFocus.kind === "heading") {
      headingRef.current?.focus();
      return;
    }
    focusOrigin(pendingFocus.key);
  }, [pendingFocus, selectValue]);

  // 브라우저 뒤로가 같은 보드의 다른 고른 것으로 가면 고치던 화의 패널이 새로 그려져 쓰던 글이 사라진다 — 카드를 고를
  // 때와 같은 확인을 받는다. 그 자리에서 연 확인이 떠 있으면 먼저 닫는다: 가려던 곳이 바뀌었고, 남겨 두면 옮긴 뒤에도
  // 옛 목적지로 묻는 모달이 화면 위에 남는다. 새로고침·창 닫기 확인(`beforeunload`)은 이 화면이 하던 일이 아니라
  // 켜지 않는다.
  useBlocker({
    shouldBlockFn: async ({ action, current, next }) => {
      const shouldConfirm = shouldConfirmDraftDiscardOnHistory({
        action,
        currentPathname: current.pathname,
        nextPathname: next.pathname,
        isDraftDirty: isDraftDirtyRef.current,
      });
      if (!shouldConfirm) return false;
      const target = resolveBoardSelection(
        parseBoardSelection(novelBoardSearchSchema.parse(next.search).select),
        novel.chapters.map((chapter) => chapter.id),
        charactersQuery.data?.map((character) => character.id),
      );
      const targetValue = target === undefined ? undefined : toBoardSelectValue(target);
      // 같은 것이면 다시 그려지지 않아 글이 남는다.
      if (targetValue === selectValue) return false;
      // 떠 있던 확인을 닫고 바로 새로 열면, 새 확인이 닫힌 뒤 돌아갈 자리로 잡는 것이 곧 사라질 옛 확인의 버튼이라
      // 포커스가 문서 처음으로 떨어진다. 그때는 머무는 패널의 제목으로 돌린다 — 키보드 사용자가 고치던 글 바로 위에서
      // 다시 이어 간다. 떠 있던 확인이 없으면 확인을 연 자리(입력칸)로 돌아가므로 손대지 않는다.
      const isReplacingConfirm = openDiscardConfirmCountRef.current > 0;
      DiscardManualEditModal.end(false);
      const isDiscarded = await confirmDiscard(target);
      if (isDiscarded) setPendingFocus(toPendingFocus(target, selection));
      else if (isReplacingConfirm) setPendingFocus({ kind: "heading", select: selectValue });
      return !isDiscarded;
    },
    enableBeforeUnload: false,
  });

  const heldChapter =
    heldChapterId !== undefined && heldChapterId !== shownChapterId
      ? novel.chapters.find((item) => item.id === heldChapterId)
      : undefined;

  async function confirmDiscard(target: BoardSelection | undefined) {
    openDiscardConfirmCountRef.current += 1;
    try {
      const chapterOrdinal =
        target?.kind === "episode" ? novel.chapters.find((item) => item.id === target.id)?.ordinal : undefined;
      return await DiscardManualEditModal.call({ chapterOrdinal });
    } finally {
      openDiscardConfirmCountRef.current -= 1;
    }
  }

  /** 주소를 옮긴다(기록에 쌓는다). 창 스크롤은 건드리지 않는다 — 라우터는 서치만 바뀐 이동에도 렌더 뒤 창을 맨 위로
   * 올리는데, 이 화면은 뷰포트 고정이라 올릴 것이 없고 패널은 새로 마운트돼 저절로 맨 위다. */
  function moveTo(next: BoardSelection | undefined, options: { replace?: boolean } = {}) {
    const nextValue = next === undefined ? undefined : toBoardSelectValue(next);
    if (next !== undefined && next.kind === "episode" && next.id === heldChapterId) setHeldChapterId(undefined);
    setPendingFocus(toPendingFocus(next, selectionRef.current));
    void navigate({
      to: "/novels/$novelId/board",
      params: { novelId: novel.id },
      search: (prev) => ({ ...prev, select: nextValue }),
      resetScroll: false,
      replace: options.replace,
    });
  }

  /** 카드·목록 행·패널 안 링크로 고른다. 고치던 글이 있으면 버릴지 먼저 묻는다. 지금 고른 것을 다시 고르면 패널을
   * 다시 그리지 않고 제목으로 포커스만 보낸다. */
  async function selectBoard(next: BoardSelection | undefined) {
    const nextValue = next === undefined ? undefined : toBoardSelectValue(next);
    if (nextValue === selectValue) {
      if (next !== undefined) headingRef.current?.focus();
      return;
    }
    if (isDraftDirtyRef.current && !(await confirmDiscard(next))) return;
    if (!isMountedRef.current) return;
    moveTo(next);
  }

  function handleChapterDeleted(firstDeletedOrdinal: number, deleted: string[]) {
    if (!isMountedRef.current) {
      // 화면을 이미 떠났으면 지운 화를 보는 구독도 없다 — 바로 버린다.
      removeDeletedChapterCaches(queryClient, novel.id, deleted);
      return;
    }
    setDeletedChapterIds(deleted);
    // 지운 화들 중 첫 화 바로 앞 화가 새 마지막 화다. 그 화를 고른다 — 지운 화를 가리키던 기록은 바꿔 쓴다(뒤로 가도
    // 없는 화다).
    const previous = novel.chapters.find((item) => item.ordinal === firstDeletedOrdinal - 1);
    moveTo(previous === undefined ? undefined : { kind: "episode", id: previous.id }, { replace: true });
  }

  const isEmpty = novel.chapters.length === 0;
  // 배치를 한 번도 받지 못했다(받은 뒤 다시 받기만 실패했으면 받은 배치로 그리고 저장해도 된다).
  const isLayoutFailed = layoutQuery.isError && layoutQuery.data === undefined;
  const showPanel = isCanvasLayout || selection !== undefined;

  return (
    <>
      <NovelBoardTopBar
        novelId={novel.id}
        title={novel.title ?? "제목 미정"}
        autosaveNotice={isCanvasLayout && !isEmpty ? "카드 자리는 자동으로 저장돼요" : undefined}
        versions={{
          isOpen: selection?.kind === "versions",
          onToggle: () => void selectBoard(selection?.kind === "versions" ? undefined : { kind: "versions" }),
        }}
        create={{
          flow,
          hasChapters: !isEmpty,
          blockedReasonId: hasChapterBlockedReason(flow) ? blockedReasonId : undefined,
          buttonRef: createButtonRef,
        }}
      />
      {/* 넓은 화면: 캔버스 + 옆 패널. 좁은 화면: 목록 ↔ 패널 화면. 패널 자리는 두 배치에서 같은 트리 자리(같은 부모의
          둘째 칸)라, 창 폭이 1024px 를 넘나들어도 패널이 다시 마운트되지 않아 쓰던 글이 남는다. */}
      <div className="flex h-below-header">
        {isCanvasLayout ? (
          <main aria-label="편집 보드" className="relative min-w-0 flex-1">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="sr-only focus-visible:not-sr-only focus-visible:absolute focus-visible:top-3 focus-visible:left-3 focus-visible:z-10"
              onClick={() => headingRef.current?.focus()}
            >
              패널로 건너뛰기
            </Button>
            {isEmpty && <EmptyCanvas onWriteNotes={() => void selectBoard({ kind: "notes" })} />}
            {!isEmpty && layoutQuery.isPending && <NovelBoardCanvasSkeleton />}
            {!isEmpty && !layoutQuery.isPending && (
              <LazyNovelBoardCanvas
                // 배치를 받지 못해 자동 배치로 그리던 캔버스는, 다시 받는 데 성공하면 새로 마운트한다 — 그대로 두면
                // 화면의 자동 배치 자리가 받은 자리를 이긴다.
                key={layoutQuery.data === undefined ? "auto-layout" : "saved-layout"}
                novelId={novel.id}
                model={model}
                savedLayout={layoutQuery.data ?? null}
                maxBytes={novel.limits.boardLayoutMaxBytes}
                canSave={canSaveBoardLayout({
                  isLayoutFailed,
                  hasCharacters: charactersQuery.data !== undefined,
                })}
                selectedNodeKey={toSelectedNodeKey(selection)}
                onSelectNode={(nodeKey) => {
                  const next = nodeKey === undefined ? undefined : nodeKeyToSelection(nodeKey);
                  if (nodeKey !== undefined && next === undefined) return;
                  void selectBoard(next);
                }}
              />
            )}
            <div className="absolute top-3 right-3 z-10 flex flex-col items-end gap-2">
              {!isEmpty && isLayoutFailed && (
                <CanvasFailedNotice
                  message="카드 자리를 불러오지 못해 자동 배치로 보여요. 옮긴 자리는 다시 불러올 때까지 저장하지 않아요."
                  onRetry={() => void layoutQuery.refetch()}
                  isRetrying={layoutQuery.isFetching}
                />
              )}
              {charactersQuery.isError && charactersQuery.data === undefined && (
                <CanvasFailedNotice
                  message="인물을 불러오지 못했어요."
                  onRetry={() => void charactersQuery.refetch()}
                  isRetrying={charactersQuery.isFetching}
                />
              )}
            </div>
          </main>
        ) : null}
        <div
          role={isCanvasLayout ? "complementary" : "main"}
          aria-label={isCanvasLayout ? "편집 패널" : "편집 보드"}
          className={
            isCanvasLayout
              ? "flex w-md shrink-0 flex-col border-l border-border bg-background xl:w-lg"
              : "flex min-w-0 flex-1 flex-col bg-background"
          }
        >
          <NovelBoardJobLine
            flow={flow}
            blockedReasonId={blockedReasonId}
            heldChapter={heldChapter}
            onOpenHeldChapter={(chapter: NovelChapterSummary) => void selectBoard({ kind: "episode", id: chapter.id })}
            createButtonRef={createButtonRef}
          />
          {!isCanvasLayout && (
            // 패널 화면이 떠 있는 동안에도 목록을 숨긴 채 둔다 — 돌아오면 고른 탭과 스크롤 자리가 그대로다.
            <div hidden={selection !== undefined} className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
              <NovelFlowList
                model={model}
                characterStatus={toCharacterStatus(charactersQuery)}
                onRetryCharacters={() => void charactersQuery.refetch()}
                onSelect={(next) => void selectBoard(next)}
              />
            </div>
          )}
          {showPanel && (
            <NovelBoardPanel
              key={selectValue ?? "overview"}
              novel={novel}
              selection={selection}
              chapterFlow={flow}
              aiEdit={aiEdit}
              headingRef={headingRef}
              onSelect={(next) => void selectBoard(next)}
              onBackToList={isCanvasLayout ? undefined : () => void selectBoard(undefined)}
              onChapterDeleted={handleChapterDeleted}
              onDraftDirtyChange={(isDirty) => {
                isDraftDirtyRef.current = isDirty;
              }}
            />
          )}
        </div>
      </div>

      {/* 버전·인물 합치기 모달은 이 화면에서만 열려 여기 마운트한다(앱 루트에 두면 첫 화면 번들이 비교 화면까지 진다). */}
      <SaveSnapshotModal />
      <RestoreSnapshotModal />
      <DeleteSnapshotModal />
      <SnapshotDiffModal />
      <MergeCharacterModal />
    </>
  );
}

/** 새로 고를 것으로 옮긴 뒤 포커스를 둘 자리. 고르면 새 패널 제목, 고르기를 풀면 풀기 전에 고르던 카드·행(버전이었으면
 * 상단 바의 버전 토글). */
function toPendingFocus(next: BoardSelection | undefined, current: BoardSelection | undefined): PendingFocus | undefined {
  if (next !== undefined) return { kind: "heading", select: toBoardSelectValue(next) };
  if (current === undefined) return undefined;
  return { kind: "origin", select: undefined, key: toBoardSelectValue(current) };
}

/** 고르기를 푼 뒤 그 대상의 카드(캔버스 노드 상자)·목록 행·버전 토글로 포커스를 돌린다. 화면 밖이라 그려지지 않은
 * 카드면 아무 데도 옮기지 않는다. */
function focusOrigin(key: string) {
  const escaped = CSS.escape(key);
  const target =
    document.querySelector(`.react-flow__node[data-id="${escaped}"]`) ??
    document.querySelector(`[data-board-key="${escaped}"]`);
  if (target instanceof HTMLElement) target.focus();
}

function toCharacterStatus(query: ReturnType<typeof useNovelCharactersQuery>): "ready" | "loading" | "error" {
  if (query.data !== undefined) return "ready";
  return query.isError ? "error" : "loading";
}

/** 화가 하나도 없을 때 캔버스 자리. 노트는 지금도 쓸 수 있어 그 입구를 둔다. */
function EmptyCanvas({ onWriteNotes }: { onWriteNotes: () => void }) {
  return (
    <div className="flex size-full items-center justify-center p-6">
      <div className="flex max-w-sm flex-col items-center gap-4 rounded-2xl border border-dashed border-border px-6 py-10 text-center break-keep">
        <p className="text-sm text-muted-foreground">
          아직 화가 없어요. 위의 "첫 화 만들기"로 대화를 소설로 만들면 화가 여기 카드로 놓여요.
        </p>
        <Button type="button" variant="outline" onClick={onWriteNotes}>
          <NotebookPen aria-hidden />
          설정 노트 쓰기
        </Button>
      </div>
    </div>
  );
}

/** 캔버스 위 실패 안내(배치·인물). 화 열은 그대로 쓸 수 있어 막지 않고 오른쪽 위에 둔다. */
function CanvasFailedNotice({ message, onRetry, isRetrying }: { message: string; onRetry: () => void; isRetrying: boolean }) {
  return (
    <div className="flex max-w-80 items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm break-keep text-muted-foreground">
      <span>{message}</span>
      <Button
        type="button"
        variant="outline"
        size="xs"
        aria-disabled={isRetrying}
        className="shrink-0 aria-disabled:opacity-65"
        onClick={() => {
          if (isRetrying) return;
          onRetry();
        }}
      >
        다시 시도
      </Button>
    </div>
  );
}

/** 상세를 받는 동안. 넓은 화면은 캔버스 자리와 패널 자리, 좁은 화면은 목록 행 막대. */
function BoardLoading() {
  const isCanvasLayout = useIsNovelBoardCanvasLayout();
  if (isCanvasLayout) {
    return (
      <div className="flex h-below-header">
        <div className="min-w-0 flex-1">
          <NovelBoardCanvasSkeleton />
        </div>
        <div aria-hidden className="flex w-md shrink-0 flex-col gap-3 border-l border-border px-6 py-6 xl:w-lg">
          <div className="h-7 w-1/2 animate-pulse rounded-lg bg-muted" />
          <div className="h-5 w-1/3 animate-pulse rounded-lg bg-muted" />
        </div>
      </div>
    );
  }
  return (
    <div role="status" className="flex h-below-header flex-col gap-2 px-4 py-4 sm:px-6">
      <span className="sr-only">보드를 불러오는 중이에요.</span>
      <div className="h-24 animate-pulse rounded-xl bg-muted" />
      <div className="h-24 animate-pulse rounded-xl bg-muted" />
      <div className="h-24 animate-pulse rounded-xl bg-muted" />
    </div>
  );
}

/** 소설을 못 보일 때(잠김·없음·실패). 상단 바는 돌아갈 길로 남기고, 제목은 안내가 갖는다. */
function BoardStatusShell({ novelId, children }: { novelId: string; children: ReactNode }) {
  return (
    <>
      <NovelBoardTopBar novelId={novelId} title={null} />
      <main className="mx-auto flex h-below-header max-w-2xl flex-col overflow-y-auto px-4 py-10 sm:px-6">{children}</main>
    </>
  );
}
