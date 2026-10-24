import { Button } from "@ai-character-chat/ui/components/button";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, RotateCcw } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { toast } from "sonner";

import { chatRoomKeys } from "@/entities/chat-room";
import { cloverKeys } from "@/entities/clover";
import {
  novelKeys,
  toNovelActionError,
  useApproveNovelOutlineMutation,
  useNovelOutlineQuery,
  useSaveNovelOutlineMutation,
  type NovelAction,
  type NovelDetailResponse,
  type NovelOutlineState,
} from "@/entities/novel";

import {
  isSameAsView,
  mergeWithNext,
  moveEpisode,
  removeEpisode,
  splitEpisode,
  toEpisodeDrafts,
  toMoveBlockedReason,
  toOutlineProblems,
  toSaveEpisodes,
  toTurnIndex,
  updateEpisodeText,
  type OutlineEpisodeDraft,
  type OutlineTurn,
} from "../model/outlineEdits";
import { toOutlineRecovery } from "../model/outlineRecovery";
import { toSelectionRevert, type SelectionRevert } from "../model/selectionRevert";
import {
  isEditBaseOutdated,
  OUTLINE_STATUS_LABEL,
  toEpisodeOrdinals,
  toMakeBlockedReason,
  toOutlineBase,
  type OutlineStatus,
} from "../model/outlineStatus";

import { OutlineEpisodeItem, type OutlineTurnsStatus } from "./OutlineEpisodeItem";

/** 구성안 만들기(유료)의 흐름과 그 상태. 작업 흐름은 다른 기능(화 만들기)에 있어 호출부가 이어 준다. */
export type OutlineMakeControl = {
  /** 모델·금액 확인을 거쳐 구성안 작업을 시작한다. */
  onStart: () => void;
  /** 확인·요청을 준비하는 중인가(버튼 아이콘이 진행 표시가 된다). */
  isPreparing: boolean;
  /** 화 작업(구성안 작업 포함)이 도는 중인가. */
  isJobRunning: boolean;
  /** 도는 작업이 전체 구성안 작업인가 — 그동안은 구성안을 고치지 않는다(끝나면 새 판이 온다). */
  isOutlineJobRunning: boolean;
  isAiEditRunning: boolean;
  /** 작업 줄의 진행 문장 id. 작업이 도는 동안 못 누르는 버튼이 이 문장을 가리킨다. */
  statusId: string;
};

type NovelOutlineStepProps = {
  novel: NovelDetailResponse;
  /** 담을 대화 단계와 같은 묶기로 만든 턴. 대화를 아직 못 받았으면 `undefined`. */
  turns: readonly OutlineTurn[] | undefined;
  isTurnsFailed: boolean;
  /** 담을 대화의 승인 상태. 방이 지워져 읽지 않으면 `undefined`. */
  selection: { hasApproved: boolean; hasPendingDraft: boolean } | undefined;
  make: OutlineMakeControl;
  /** 낡은 구성안이 쓴 구간을 담을 대화 단계에 되돌린다 — 그 구성안이 쓴 선택의 담기 구간이면 양 끝 그대로, 그 칸이 없으면 화들의
   * 근거로 어림한 구간이다. */
  onRevertSelection: (revert: Exclude<SelectionRevert, { kind: "sourceChanged" }>) => void;
  onDraftDirtyChange: (isDirty: boolean) => void;
};

type Edits = { baseRevision: number; episodes: OutlineEpisodeDraft[] };

type StepNotice = { tone: "error" | "done"; message: string };

/**
 * 구성 2단계 "전체 구성안" — 승인한 담을 대화를 화로 나눈 안. 만들기는 유료(모델·금액 확인)이고, 화마다 제목·줄거리·목표를 고치고
 * 차례를 바꾸고 이웃 화를 합치거나 턴 사이에서 나눈 뒤 "초안 저장"·"이대로 승인"으로 서버에 보낸다(둘 다 무료). 승인한 판은 바뀌지
 * 않고, 고치면 새 초안이 된다.
 *
 * 담을 대화를 바꿔 이 구성안의 근거 구간이 빠졌으면 낡음이다 — 고치거나 승인할 수 없고, 다시 만들거나 구간을 되돌린다. 원래
 * 대화방이 지워졌으면 보기와 승인만 된다(서버가 만들기·저장을 막는다).
 */
export function NovelOutlineStep(props: NovelOutlineStepProps) {
  const query = useNovelOutlineQuery(props.novel.id, { enabled: true });
  const queryClient = useQueryClient();
  const error = query.error;

  // 스위치를 막 껐으면 가격을 다시 받아 구성 화면을 거둔다.
  useEffect(() => {
    if (error === null || toOutlineRecovery(error).refetchPricing === false) return;
    toast("지금은 구성 흐름을 쓸 수 없어요.");
    void queryClient.invalidateQueries({ queryKey: cloverKeys.pricing() });
  }, [error]);

  if (query.data === undefined) {
    if (!query.isError) {
      return (
        <StepShell status={undefined}>
          <div role="status" className="flex flex-col gap-2">
            <span className="sr-only">전체 구성안을 불러오는 중이에요.</span>
            <div aria-hidden className="h-24 animate-pulse rounded-xl bg-muted" />
            <div aria-hidden className="h-24 animate-pulse rounded-xl bg-muted" />
          </div>
        </StepShell>
      );
    }
    return (
      <StepShell status={undefined}>
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm break-keep text-muted-foreground">전체 구성안을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-disabled={query.isFetching}
            className="aria-disabled:opacity-65"
            onClick={() => {
              if (query.isFetching) return;
              void query.refetch();
            }}
          >
            다시 시도
          </Button>
        </div>
      </StepShell>
    );
  }
  return <OutlineEditor {...props} state={query.data} />;
}

function OutlineEditor({
  novel,
  turns,
  isTurnsFailed,
  selection,
  make,
  onRevertSelection,
  onDraftDirtyChange,
  state,
}: NovelOutlineStepProps & { state: NovelOutlineState }) {
  const queryClient = useQueryClient();
  const saveMutation = useSaveNovelOutlineMutation();
  const approveMutation = useApproveNovelOutlineMutation();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const makeReasonId = useId();
  const [edits, setEdits] = useState<Edits | undefined>(undefined);
  const [editingId, setEditingId] = useState<string | undefined>(undefined);
  const [splittingId, setSplittingId] = useState<string | undefined>(undefined);
  const [notice, setNotice] = useState<StepNotice | undefined>(undefined);
  const [busy, setBusy] = useState<"save" | "approve" | undefined>(undefined);
  // 구조를 바꾼 뒤 포커스를 둘 자리(선택자). 바뀐 목록이 그려진 뒤 옮긴다.
  const [pendingFocus, setPendingFocus] = useState<string | undefined>(undefined);
  const newIdRef = useRef(0);

  const base = toOutlineBase(state);
  const isRoomGone = novel.chatRoomId === null;
  const turnIndex = useMemo(() => (turns === undefined ? undefined : toTurnIndex(turns)), [turns]);
  const turnsStatus = toTurnsStatus({ isRoomGone, isReady: turnIndex !== undefined, isFailed: isTurnsFailed });

  // 서버 판이 바뀌었는데(다른 탭의 저장·새 구성안 작업) 이 화면의 고침이 옛 판 위에 있으면 저장 때 서버가 409 로 막는다 — 그때
  // 고침을 버리고 새 판을 받는다(`toOutlineRecovery`).
  const episodes = edits?.episodes ?? (base === undefined ? [] : toEpisodeDrafts(base.view));
  const isDirty = base !== undefined && edits !== undefined && !isSameAsView(edits.episodes, base.view);
  const isFormOpen = editingId !== undefined;
  const ordinals = toEpisodeOrdinals(episodes, novel.chapters);
  const titleMaxLength = novel.limits.chapterTitleMaxLength;
  const canEdit = base !== undefined && !base.isStale && !isRoomGone && !make.isOutlineJobRunning && busy === undefined;

  useEffect(() => {
    onDraftDirtyChange(isDirty || isFormOpen);
  }, [isDirty, isFormOpen]);
  useEffect(() => () => onDraftDirtyChange(false), []);

  // 고치는 사이 새 판이 왔다(구성안 작업의 다시 시도·다른 탭) — 옛 판 위의 고침은 저장해도 409 로 버려지므로 지금 버리고 알린다.
  const latestRevision = base?.view.revision;
  useEffect(() => {
    // 저장·승인 중에는 이 화면이 낸 새 판이다 — 저장이 끝나며 고침을 비운다.
    if (busy !== undefined || !isEditBaseOutdated(edits?.baseRevision, latestRevision)) return;
    setEdits(undefined);
    setEditingId(undefined);
    setSplittingId(undefined);
    setNotice({ tone: "error", message: "그사이 새 구성안이 와서 고치던 것은 버렸어요. 새 구성안을 확인해주세요." });
  }, [latestRevision]);

  useEffect(() => {
    if (pendingFocus === undefined) return;
    setPendingFocus(undefined);
    const target = document.querySelector(pendingFocus);
    if (target instanceof HTMLElement) target.focus();
    else headingRef.current?.focus();
  }, [pendingFocus]);

  const makeBlockedReason = toMakeBlockedReason({
    isRoomGone,
    isJobRunning: make.isJobRunning,
    isAiEditRunning: make.isAiEditRunning,
    // 방이 지워진 소설은 담을 대화를 읽지 않는다 — 그때는 방 없음이 먼저라 이 값은 쓰이지 않는다.
    hasApprovedSelection: selection?.hasApproved,
    isDirty: isDirty || isFormOpen,
  });
  const isMakeBlocked = makeBlockedReason !== undefined || make.isPreparing;

  function edit(next: OutlineEpisodeDraft[]) {
    if (base === undefined) return;
    setNotice(undefined);
    setEdits({ baseRevision: edits?.baseRevision ?? base.view.revision, episodes: next });
  }

  function nextLocalId() {
    newIdRef.current += 1;
    return `split-${newIdRef.current}`;
  }

  function handleError(error: unknown, action: NovelAction) {
    const result = toNovelActionError(error, action);
    const recovery = toOutlineRecovery(error);
    if (recovery.resetEdits) {
      setEdits(undefined);
      setEditingId(undefined);
      setSplittingId(undefined);
    }
    if (recovery.refetchOutline) void queryClient.invalidateQueries({ queryKey: novelKeys.outline(novel.id) });
    if (recovery.refetchMessages && novel.chatRoomId !== null) {
      void queryClient.invalidateQueries({ queryKey: chatRoomKeys.sourceMessages(novel.chatRoomId) });
    }
    if (recovery.refetchPricing) {
      // 가격을 다시 받으면 구성 화면이 거둬져 이 안내도 함께 사라진다 — 화면 밖에 남는 알림으로 말한다.
      if (result !== null) toast(result.message);
      void queryClient.invalidateQueries({ queryKey: cloverKeys.pricing() });
      return;
    }
    if (result === null) return;
    setNotice({ tone: "error", message: result.message });
    if (result.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
  }

  /** 고친 구성안을 새 초안으로 저장한다. 고칠 것이 남았으면 보내지 않고 그 문장을 보인다(서버가 같은 이유로 막는다). */
  async function saveDraft(): Promise<NovelOutlineState | undefined> {
    if (edits === undefined) return state;
    const problems = toOutlineProblems(edits.episodes, ordinals, { titleMaxLength, maxEpisodes: state.maxEpisodes });
    if (problems.length > 0) {
      setNotice({ tone: "error", message: problems.join(" ") });
      return undefined;
    }
    const saved = await saveMutation.mutateAsync({
      novelId: novel.id,
      body: { baseRevision: edits.baseRevision, episodes: toSaveEpisodes(edits.episodes) },
    });
    setEdits(undefined);
    return saved;
  }

  async function handleSave() {
    if (busy !== undefined || isFormOpen) return;
    setNotice(undefined);
    setBusy("save");
    try {
      const saved = await saveDraft();
      if (saved !== undefined) {
        setNotice({ tone: "done", message: "초안을 저장했어요. 승인하면 다음 단계로 이어져요." });
        // 저장하면 고친 것이 없어져 누른 "초안 저장"이 사라진다 — 포커스가 떨어지지 않게 단계 제목으로 옮긴다.
        headingRef.current?.focus();
      }
    } catch (error) {
      handleError(error, "saveOutline");
    } finally {
      setBusy(undefined);
    }
  }

  async function handleApprove() {
    if (busy !== undefined || isFormOpen) return;
    setNotice(undefined);
    setBusy("approve");
    let action: NovelAction = "saveOutline";
    try {
      const current = isDirty ? await saveDraft() : state;
      if (current === undefined) return;
      action = "approveOutline";
      const revision = current.draft?.revision;
      if (revision !== undefined) await approveMutation.mutateAsync({ novelId: novel.id, revision });
      setNotice({ tone: "done", message: "전체 구성안을 승인했어요." });
      // 승인하면 저장·승인 버튼이 사라진다 — 누른 버튼과 함께 포커스가 떨어지지 않게 단계 제목으로 옮긴다.
      headingRef.current?.focus();
    } catch (error) {
      handleError(error, action);
    } finally {
      setBusy(undefined);
    }
  }

  function handleReset() {
    if (busy !== undefined) return;
    setEdits(undefined);
    setEditingId(undefined);
    setSplittingId(undefined);
    setNotice(undefined);
    headingRef.current?.focus();
  }

  if (base === undefined) {
    return (
      <StepShell status={undefined} headingRef={headingRef}>
        <p className="text-sm break-keep text-muted-foreground">
          {selection?.hasApproved === false
            ? "담을 대화를 승인하면, 그 대화를 화로 나눈 구성안을 만들 수 있어요."
            : "담은 대화를 화로 나눈 구성안을 만들어요. 화마다 제목·줄거리·목표와 근거가 된 대화가 붙고, 고친 뒤 승인해요."}
        </p>
        {make.isOutlineJobRunning && <OutlineJobRunningLine />}
        <MakeButton
          label="구성안 만들기"
          variant="secondary"
          make={make}
          isBlocked={isMakeBlocked}
          blockedReason={makeBlockedReason}
          reasonId={makeReasonId}
        />
      </StepShell>
    );
  }

  const status: OutlineStatus = base.status;
  // 낡은 판만 되돌릴 구간을 따진다(서버가 낡은 판에만 그 선택의 구간을 싣는다).
  const revert = base.isStale ? toSelectionRevert(base.view) : undefined;
  const isApproveShown = !base.isStale && (status !== "approved" || isDirty);
  const isActionBusy = busy !== undefined || isFormOpen;
  return (
    <StepShell status={status} isStale={base.isStale} headingRef={headingRef}>
      {selection?.hasPendingDraft === true && (
        <p className="text-sm break-keep text-muted-foreground">
          담을 대화에 승인하지 않은 고침이 있어요. 구성안은 승인한 담을 대화로 만들어요.
        </p>
      )}
      {base.isStale && (
        <div className="flex flex-col gap-3 rounded-lg border border-border px-4 py-3">
          <p className="text-sm break-keep text-foreground">
            {revert?.kind === "sourceChanged"
              ? "구성안을 만든 뒤 대화 원문이 바뀌어 이 구성안은 낡았어요. 원문이 바뀐 대화는 구간을 되돌려도 그대로 돌아오지 않아요. 구성안을 다시 만들어주세요."
              : "담을 대화를 바꿔 이 구성안이 근거로 쓴 대화가 빠졌어요(낡음). 낡은 구성안은 고치거나 승인할 수 없어요. 다시 만들거나, 빠진 대화를 다시 담아 승인해주세요."}
          </p>
          <div className="flex flex-wrap gap-2">
            <MakeButton
              label="다시 만들기"
              variant="outline"
              make={make}
              isBlocked={isMakeBlocked}
              blockedReason={makeBlockedReason}
              reasonId={makeReasonId}
            />
            {!isRoomGone && revert !== undefined && revert.kind !== "sourceChanged" && (
              <Button type="button" variant="outline" size="sm" onClick={() => onRevertSelection(revert)}>
                <RotateCcw aria-hidden />
                구간 되돌리기
              </Button>
            )}
          </div>
        </div>
      )}
      {isRoomGone && (
        <p className="text-sm break-keep text-muted-foreground">
          원래 대화방이 지워져 구성안을 새로 만들거나 고칠 수 없어요. 지금 구성안을 보고 승인할 수는 있어요.
        </p>
      )}
      {make.isOutlineJobRunning && <OutlineJobRunningLine />}

      <ol aria-label="구성안 화" className="flex flex-col gap-3">
        {episodes.map((episode, index) => (
          <OutlineEpisodeItem
            key={episode.localId}
            episode={episode}
            ordinal={ordinals[index] ?? index + 1}
            count={episodes.length}
            turnIndex={turnIndex}
            turnsStatus={turnsStatus}
            canEdit={canEdit && (editingId === undefined || editingId === episode.localId)}
            isEditing={editingId === episode.localId}
            isSplitting={splittingId === episode.localId}
            mergeBlockedReason={toMergeBlockedReason(episodes, episode.localId, turnIndex)}
            moveBlockedReasons={{
              up: toMoveBlockedReason(episodes, episode.localId, -1),
              down: toMoveBlockedReason(episodes, episode.localId, 1),
            }}
            titleMaxLength={titleMaxLength}
            onEdit={() => {
              setSplittingId(undefined);
              setEditingId(episode.localId);
            }}
            onApply={(text) => {
              edit(updateEpisodeText(episodes, episode.localId, text));
              setEditingId(undefined);
              setPendingFocus(`[data-outline-edit="${episode.localId}"]`);
            }}
            onCancelEdit={() => {
              setEditingId(undefined);
              setPendingFocus(`[data-outline-edit="${episode.localId}"]`);
            }}
            onMove={(delta) => {
              edit(moveEpisode(episodes, episode.localId, delta));
              setPendingFocus(`[data-outline-menu="${episode.localId}"]`);
            }}
            onMerge={() => {
              const result = mergeWithNext(episodes, episode.localId, turnIndex);
              if ("reason" in result) return;
              edit(result.episodes);
              setSplittingId(undefined);
              // 줄거리·목표를 이어 붙였다 — 바로 다듬게 고치기를 연다.
              setEditingId(episode.localId);
            }}
            onStartSplit={() => {
              setEditingId(undefined);
              setSplittingId(episode.localId);
              setPendingFocus("[data-outline-split-cancel]");
            }}
            onCancelSplit={() => {
              setSplittingId(undefined);
              setPendingFocus(`[data-outline-menu="${episode.localId}"]`);
            }}
            onSplit={(cutMessageId) => {
              if (turnIndex === undefined) return;
              const newId = nextLocalId();
              const next = splitEpisode(episodes, episode.localId, cutMessageId, turnIndex, newId, { titleMaxLength });
              if (next === undefined) return;
              edit(next);
              setSplittingId(undefined);
              // 뒤 화는 앞 화의 글을 그대로 가졌다 — 바로 고치게 고치기를 연다.
              setEditingId(newId);
            }}
            onRemove={() => {
              const next = removeEpisode(episodes, episode.localId);
              const neighbor = next[Math.min(index, next.length - 1)];
              edit(next);
              // 지운 화의 메뉴가 사라진다 — 그 자리에 온 이웃 화의 메뉴로 포커스를 옮긴다.
              if (neighbor !== undefined) setPendingFocus(`[data-outline-menu="${neighbor.localId}"]`);
            }}
          />
        ))}
      </ol>

      {notice?.tone === "error" && (
        <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text">
          {notice.message}
        </p>
      )}
      {notice?.tone === "done" && (
        <p role="status" className="text-sm break-keep text-muted-foreground">
          {notice.message}
        </p>
      )}
      {status === "approved" && !isDirty && !base.isStale && (
        <p className="text-sm break-keep text-muted-foreground">승인한 구성안이에요. 고치면 새 초안이 되고, 다시 승인해야 해요.</p>
      )}
      {isFormOpen && (
        <p className="text-sm break-keep text-muted-foreground">고치던 화를 적용하거나 취소한 뒤 저장할 수 있어요.</p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {!base.isStale && (
          <MakeButton
            label="다시 만들기"
            variant="ghost"
            make={make}
            isBlocked={isMakeBlocked}
            blockedReason={makeBlockedReason}
            reasonId={makeReasonId}
          />
        )}
        <div className="ml-auto flex flex-wrap justify-end gap-2">
          {isDirty && (
            <Button type="button" variant="ghost" aria-disabled={isActionBusy} className="aria-disabled:opacity-65" onClick={handleReset}>
              고친 것 되돌리기
            </Button>
          )}
          {isDirty && !base.isStale && (
            <Button
              type="button"
              variant="outline"
              aria-disabled={isActionBusy}
              className="aria-disabled:opacity-65"
              onClick={() => void handleSave()}
            >
              {busy === "save" && <Loader2 aria-hidden className="animate-spin" />}
              초안 저장
            </Button>
          )}
          {isApproveShown && (
            <Button
              type="button"
              variant="secondary"
              aria-disabled={isActionBusy || make.isOutlineJobRunning}
              className="aria-disabled:opacity-65"
              onClick={() => {
                if (make.isOutlineJobRunning) return;
                void handleApprove();
              }}
            >
              {busy === "approve" && <Loader2 aria-hidden className="animate-spin" />}
              이대로 승인
            </Button>
          )}
        </div>
      </div>
    </StepShell>
  );
}

function toTurnsStatus(status: { isRoomGone: boolean; isReady: boolean; isFailed: boolean }): OutlineTurnsStatus {
  if (status.isRoomGone) return "gone";
  if (status.isReady) return "ready";
  return status.isFailed ? "error" : "loading";
}

function toMergeBlockedReason(
  episodes: readonly OutlineEpisodeDraft[],
  localId: string,
  turnIndex: ReturnType<typeof toTurnIndex> | undefined,
): string | undefined {
  const result = mergeWithNext(episodes, localId, turnIndex);
  return "reason" in result ? result.reason : undefined;
}

function OutlineJobRunningLine() {
  return (
    <p className="flex items-center gap-2 text-sm break-keep text-muted-foreground">
      <Loader2 aria-hidden className="size-4 shrink-0 animate-spin" />
      전체 구성안을 만들고 있어요. 끝나면 새 초안이 여기 와요.
    </p>
  );
}

type MakeButtonProps = {
  label: string;
  variant: "secondary" | "outline" | "ghost";
  make: OutlineMakeControl;
  isBlocked: boolean;
  blockedReason: string | undefined;
  reasonId: string;
};

/** 구성안 만들기·다시 만들기(유료 — 누르면 모델·금액 확인이 뜬다). 못 누르는 동안에도 `aria-disabled` 로 남기고 이유 한 줄을 단다.
 * 작업이 도는 동안의 이유는 작업 줄의 진행 문장을 함께 가리킨다. */
function MakeButton({ label, variant, make, isBlocked, blockedReason, reasonId }: MakeButtonProps) {
  const describedBy = [blockedReason === undefined ? undefined : reasonId, make.isJobRunning ? make.statusId : undefined]
    .filter((id) => id !== undefined)
    .join(" ");
  return (
    <div className="flex flex-col items-start gap-1.5">
      <Button
        type="button"
        variant={variant}
        size="sm"
        aria-disabled={isBlocked}
        aria-describedby={isBlocked && describedBy !== "" ? describedBy : undefined}
        className="aria-disabled:opacity-65"
        onClick={() => {
          if (isBlocked) return;
          make.onStart();
        }}
      >
        {make.isPreparing && <Loader2 aria-hidden className="animate-spin" />}
        {label}
      </Button>
      {blockedReason !== undefined && (
        <p id={reasonId} className="text-xs break-keep text-muted-foreground">
          {blockedReason}
        </p>
      )}
    </div>
  );
}

type StepShellProps = {
  status: OutlineStatus | undefined;
  isStale?: boolean;
  headingRef?: RefObject<HTMLHeadingElement | null>;
  children: ReactNode;
};

/** 단계의 제목·상태 표시와 본문 자리. */
function StepShell({ status, isStale = false, headingRef, children }: StepShellProps) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {/* 저장·승인 뒤 포커스를 받아 두는 자리라 `tabIndex=-1` 이고 포커스 테두리를 그리지 않는다. */}
        <h3 id={headingId} ref={headingRef} tabIndex={-1} className="text-lg font-semibold text-foreground outline-none">
          전체 구성안
        </h3>
        {status !== undefined && (
          <span className="rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground">
            {OUTLINE_STATUS_LABEL[status]}
          </span>
        )}
        {isStale && (
          <span className="rounded-full border border-border px-2 py-0.5 text-badge font-medium text-foreground">낡음</span>
        )}
      </div>
      {children}
    </section>
  );
}
