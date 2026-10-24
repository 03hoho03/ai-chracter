import { Button } from "@ai-character-chat/ui/components/button";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode, type RefObject } from "react";
import { toast } from "sonner";

import { chatRoomKeys, useChatRoomSourceMessagesQuery } from "@/entities/chat-room";
import { cloverKeys } from "@/entities/clover";
import {
  hasNovelErrorCode,
  novelKeys,
  toNovelActionError,
  useApproveNovelSourceSelectionMutation,
  useNovelSourceSelectionQuery,
  useSaveNovelSourceSelectionMutation,
  type NovelAction,
  type NovelDetailResponse,
  type NovelSourceSelectionState,
} from "@/entities/novel";

import { toSelectionRecovery } from "../model/selectionRecovery";
import {
  hasChangedSource,
  isFixedEndLost,
  SOURCE_SELECTION_STATUS_LABEL,
  toSaveRoomEnd,
  toSourceSelectionBase,
  toSourceSelectionStatus,
} from "../model/selectionStatus";
import {
  buildSourceTurns,
  countTurnStates,
  hasIncludedResponse,
  includeTurnsInRanges,
  isSameStates,
  placeRangesByKey,
  restoreIncludeRanges,
  setTurnRange,
  setTurnsState,
  toBaseStates,
  toChangedTurnKeys,
  toggleTurn,
  toSaveSections,
  type SourceRange,
  type SourceTurn,
  type TurnState,
} from "../model/sourceTimeline";

import { SourceTimeline } from "./SourceTimeline";

type NovelSourceSelectionStepProps = {
  novel: NovelDetailResponse;
  /** 저장하지 않은 고침이 있는가를 알린다 — 보드가 다른 곳으로 옮기기 전에 버릴지 묻는다. */
  onDraftDirtyChange: (isDirty: boolean) => void;
  /** 되돌려 달라는 대화 구간(낡은 구성안이 쓴 구간). `id` 가 바뀔 때마다 한 번 고침을 만든다. `isExact` 면 그 구성안이 쓴 선택의 담기
   * 구간이라 양 끝 그대로 되돌리고, 아니면(화들의 근거로 어림한 구간) 그 구간의 턴을 담기로 바꾸기만 한다. */
  restoreRequest?: { id: number; ranges: readonly SourceRange[]; isExact: boolean };
};

/** 화면이 고친 선택. 고치기 시작한 판의 리비전을 들고 있다가 저장 때 보낸다 — 그사이 다른 탭이 저장했으면 서버가 409 로 막아,
 * 낡은 판 위의 고침이 남의 저장을 덮지 않는다. */
type Edits = { baseRevision: number | null; states: Map<string, TurnState>; isExtended: boolean };

type StepNotice = { tone: "error" | "done"; message: string };

/**
 * 구성 1단계 "담을 대화" — 대화방의 어느 턴을 소설에 담고(담기), 앞뒤 사정으로만 보내고(맥락), 뺄지(빼기) 고른다. 저장·승인은
 * 무료다. 이미 화로 쓴 대화는 담을 수 없다.
 *
 * 처음에는 서버의 기본 제안(아직 쓰지 않은 대화를 모두 담기)이나 저장된 최신 판을 보이고, 고치면 이 화면에만 있다가 "초안
 * 저장"·"이대로 승인"으로 서버에 간다. 고른 뒤 대화가 이어졌으면 저절로 붙이지 않고 "새 구간 추가"로 연다.
 */
export function NovelSourceSelectionStep({ novel, onDraftDirtyChange, restoreRequest }: NovelSourceSelectionStepProps) {
  if (novel.chatRoomId === null) {
    return (
      <StepShell status={undefined}>
        <p className="text-sm break-keep text-muted-foreground">
          원래 대화방이 지워져 담을 대화를 고를 수 없어요. 이미 만든 화는 그대로예요.
        </p>
      </StepShell>
    );
  }
  return (
    <SelectionLoader
      novel={novel}
      roomId={novel.chatRoomId}
      onDraftDirtyChange={onDraftDirtyChange}
      restoreRequest={restoreRequest}
    />
  );
}

function SelectionLoader({
  novel,
  roomId,
  onDraftDirtyChange,
  restoreRequest,
}: NovelSourceSelectionStepProps & { roomId: string }) {
  const queryClient = useQueryClient();
  const selectionQuery = useNovelSourceSelectionQuery(novel.id, { enabled: true });
  const messagesQuery = useChatRoomSourceMessagesQuery(roomId, { enabled: true });
  const selectionError = selectionQuery.error;

  // 조회가 스위치 꺼짐·방 없음으로 막혔다 — 가격·상세를 다시 받으면 보드가 구성 화면을 거두거나 방 없음 안내로 바꾼다.
  useEffect(() => {
    if (selectionError === null) return;
    if (hasNovelErrorCode(selectionError, "NOVEL_OUTLINE_FLOW_DISABLED")) {
      toast("지금은 구성 흐름을 쓸 수 없어요.");
      void queryClient.invalidateQueries({ queryKey: cloverKeys.pricing() });
    }
    if (hasNovelErrorCode(selectionError, "NOVEL_ROOM_GONE")) {
      void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
    }
  }, [selectionError]);

  const state = selectionQuery.data;
  const messages = messagesQuery.data;
  if (state === undefined || messages === undefined) {
    const failed = (selectionQuery.isError && state === undefined) || (messagesQuery.isError && messages === undefined);
    if (!failed) {
      return (
        <StepShell status={undefined}>
          <div role="status" className="flex flex-col gap-2">
            <span className="sr-only">담을 대화를 불러오는 중이에요.</span>
            <div aria-hidden className="h-16 animate-pulse rounded-lg bg-muted" />
            <div aria-hidden className="h-16 animate-pulse rounded-lg bg-muted" />
            <div aria-hidden className="h-16 animate-pulse rounded-lg bg-muted" />
          </div>
        </StepShell>
      );
    }
    const isRetrying = selectionQuery.isFetching || messagesQuery.isFetching;
    return (
      <StepShell status={undefined}>
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm break-keep text-muted-foreground">담을 대화를 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-disabled={isRetrying}
            className="aria-disabled:opacity-65"
            onClick={() => {
              if (isRetrying) return;
              if (selectionQuery.isError) void selectionQuery.refetch();
              if (messagesQuery.isError) void messagesQuery.refetch();
            }}
          >
            다시 시도
          </Button>
        </div>
      </StepShell>
    );
  }
  return (
    <SelectionEditor
      novel={novel}
      roomId={roomId}
      state={state}
      messages={messages}
      isMessagesFetching={messagesQuery.isFetching}
      onRefetchMessages={() => void messagesQuery.refetch()}
      onDraftDirtyChange={onDraftDirtyChange}
      restoreRequest={restoreRequest}
    />
  );
}

type SelectionEditorProps = NovelSourceSelectionStepProps & {
  roomId: string;
  state: NovelSourceSelectionState;
  messages: Parameters<typeof buildSourceTurns>[0];
  isMessagesFetching: boolean;
  onRefetchMessages: () => void;
};

function SelectionEditor({
  novel,
  roomId,
  state,
  messages,
  isMessagesFetching,
  onRefetchMessages,
  onDraftDirtyChange,
  restoreRequest,
}: SelectionEditorProps) {
  const queryClient = useQueryClient();
  const saveMutation = useSaveNovelSourceSelectionMutation();
  const approveMutation = useApproveNovelSourceSelectionMutation();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const helpId = useId();
  const [edits, setEdits] = useState<Edits | undefined>(undefined);
  // Shift 이어 바꾸기의 시작점 — 마지막으로 누른 턴.
  const [anchorKey, setAnchorKey] = useState<string | undefined>(undefined);
  const [expandedGapKeys, setExpandedGapKeys] = useState<ReadonlySet<string>>(new Set());
  const [notice, setNotice] = useState<StepNotice | undefined>(undefined);
  const [busy, setBusy] = useState<"save" | "approve" | undefined>(undefined);
  // 승인한 선택은 타임라인을 접고 요약 한 줄만 둔다 — 수백 턴 타임라인 아래에 다음 단계(전체 구성안)가 묻히지 않게. 펼치면 고칠 수
  // 있다.
  const [isExpanded, setIsExpanded] = useState(false);
  const handledRestoreIdRef = useRef<number | undefined>(undefined);
  // 턴이나 묶음 버튼을 누르면 그 턴이 다른 묶음으로 옮겨 다시 그려진다 — 커밋 뒤 그 턴(접혔으면 그 턴이 든 묶음의 버튼)으로
  // 포커스를 둔다.
  const [pendingFocusTurn, setPendingFocusTurn] = useState<number | undefined>(undefined);

  const base = toSourceSelectionBase(state);
  const status = toSourceSelectionStatus(state);
  const fixedEndId = base?.view.roomEndMessageId ?? null;
  const allTurns = buildSourceTurns(messages, {
    fixedEndId,
    fixedEndCreatedAt: base?.view.roomEndMessageCreatedAt,
    roomEndId: state.roomEndMessageId,
    lockedRanges: state.lockedRanges,
  });
  // 끝 메시지가 지워진 구간도 키로 지금 있는 메시지에 맞춘다(키를 모르면 그대로 — 턴 상태를 펴며 이웃으로 어림한다).
  const sections = placeRangesByKey(messages, base?.view.sections ?? []);
  const isExtended = edits?.isExtended ?? false;
  const turns = isExtended ? allTurns : allTurns.filter((turn) => !turn.isNew);
  const newTurnCount = allTurns.filter((turn) => turn.isNew).length;
  const baseStates = toBaseStates(allTurns, sections);
  const states = edits?.states ?? baseStates;
  const isDirty = edits !== undefined && (edits.isExtended || !isSameStates(turns, edits.states, baseStates));
  const changedKeys = toChangedTurnKeys(allTurns, sections);
  const isSourceChanged = base !== undefined && hasChangedSource(base.view);
  // 서버에 보낼 것이 있는가 — 고쳤거나, 아직 한 번도 저장하지 않았거나(제안), 저장 뒤 원문이 바뀌어 지금 원문으로 다시 저장해야
  // 승인할 수 있다.
  const needsSave = isDirty || status === "unsaved" || isSourceChanged;
  const counts = countTurnStates(turns, states);

  // 화면이 본 방 끝을 아직 메시지 목록이 모른다(조회 사이에 대화가 이어졌다) — 한 번 다시 받는다.
  const roomEndId = state.roomEndMessageId;
  const isMessagesBehind = roomEndId !== null && !messages.some((message) => message.id === roomEndId);
  // 고른 때의 마지막 메시지가 지금 대화에 없고(마지막 답을 다시 만들었거나 지웠다) 키로도 자리를 잡을 수 없다. 저장된 판에서만 있는
  // 일이다 — 제안의 고정 끝은 지금 방 끝이다. 키로 자리를 잡으면 다시 쓴 답은 고른 뒤 이어진 새 대화로 보인다.
  const isFixedEndMissing =
    status !== "unsaved" && !isMessagesBehind && base !== undefined && isFixedEndLost(messages, base.view);
  const refetchedForRef = useRef<string | null>(null);
  useEffect(() => {
    if (!isMessagesBehind || isMessagesFetching || refetchedForRef.current === roomEndId) return;
    refetchedForRef.current = roomEndId;
    onRefetchMessages();
  }, [isMessagesBehind, isMessagesFetching, roomEndId]);

  useEffect(() => {
    onDraftDirtyChange(isDirty);
  }, [isDirty]);
  useEffect(() => () => onDraftDirtyChange(false), []);

  // 되돌려 달라는 구간이 왔다(낡은 구성안의 "구간 되돌리기"). 고침을 만들고 타임라인을 펼쳐 이 단계 제목으로 포커스를 옮긴다 —
  // 이용자가 확인한 뒤 승인한다.
  useEffect(() => {
    if (restoreRequest === undefined || handledRestoreIdRef.current === restoreRequest.id) return;
    handledRestoreIdRef.current = restoreRequest.id;
    setIsExpanded(true);
    setNotice({ tone: "done", message: restoreRequest.isExact ? restoreExactly(restoreRequest.ranges) : restoreRoughly(restoreRequest.ranges) });
    headingRef.current?.focus();
  }, [restoreRequest?.id]);

  /** 그 구성안이 쓴 선택의 담기 구간을 양 끝 그대로 되돌린다. 그대로 고를 수 없으면(대화 묶음이 달라졌거나 그 대화가 화가 됐다)
   * 아무것도 바꾸지 않고 다시 만들라고 말한다. 돌려준 것은 알릴 문장이다. */
  function restoreExactly(ranges: readonly SourceRange[]): string {
    const restored = restoreIncludeRanges(turns, states, ranges);
    if (restored === undefined) return "구성안을 만든 때의 구간을 지금 대화에서 그대로 고를 수 없어요. 구성안을 다시 만들어주세요.";
    if (restored.included === 0 && restored.excluded === 0) {
      return "구성안을 만든 때의 담을 대화와 이미 같아요. 승인하면 구성안을 다시 쓸 수 있어요.";
    }
    edit(restored.states);
    const split =
      restored.excluded > 0
        ? ` 이어 붙어 있던 다른 턴 ${restored.excluded.toLocaleString()}턴은 구간이 합쳐지지 않게 뺐어요.`
        : "";
    return `구성안을 만든 때의 담을 대화로 되돌렸어요. 확인한 뒤 승인하면 구성안을 다시 쓸 수 있어요.${split}`;
  }

  /** 화들의 근거로 어림한 구간의 턴을 담기로 바꾼다. 구성안이 낡은 까닭이 구간을 뺀 것이 아니면(구간 끝·원문이 바뀜) 다시 담을 턴이
   * 없거나 담아도 낡음이 남는다 — 그때는 다시 만들라고 말한다. */
  function restoreRoughly(ranges: readonly SourceRange[]): string {
    const restored = includeTurnsInRanges(turns, states, ranges);
    if (restored.count === 0) {
      return "구성안의 화들이 근거로 쓴 대화는 이미 모두 담겨 있어요. 그래도 낡음이 남으면 구성안을 다시 만들어주세요.";
    }
    edit(restored.states);
    return `구성안이 쓴 대화 ${restored.count.toLocaleString()}턴을 다시 담았어요. 확인한 뒤 승인하면 구성안을 다시 쓸 수 있어요. 그래도 낡음이 남으면 구성안을 다시 만들어주세요.`;
  }

  useEffect(() => {
    if (pendingFocusTurn === undefined) return;
    setPendingFocusTurn(undefined);
    focusTurn(pendingFocusTurn);
  }, [pendingFocusTurn]);

  function edit(next: Map<string, TurnState>, options: { isExtended?: boolean } = {}) {
    setNotice(undefined);
    setEdits({
      baseRevision: edits?.baseRevision ?? base?.baseRevision ?? null,
      states: next,
      isExtended: options.isExtended ?? isExtended,
    });
  }

  function handleToggleTurn(turn: SourceTurn, { isRange }: { isRange: boolean }) {
    // 잠긴 턴은 담을 수 없다 — 맥락으로 보낸 잠긴 턴은 묶음의 "맥락에서 빼기"로만 바꾼다.
    if (busy !== undefined || turn.isLocked) return;
    const anchor = isRange && anchorKey !== undefined && turns.some((item) => item.key === anchorKey) ? anchorKey : undefined;
    if (anchor === undefined) edit(toggleTurn(states, turn));
    else edit(setTurnRange(states, turns, anchor, turn.key, states.get(turn.key) === "include" ? "exclude" : "include"));
    setAnchorKey(turn.key);
    // 상태가 바뀐 턴은 다른 묶음으로 옮겨 다시 그려진다 — 누른 줄에 포커스를 되돌린다.
    setPendingFocusTurn(turn.number);
  }

  function handleSetGap(segmentTurns: readonly SourceTurn[], target: "context" | "exclude") {
    if (busy !== undefined) return;
    edit(
      setTurnsState(
        states,
        turns,
        segmentTurns.map((turn) => turn.key),
        target,
      ),
    );
    setPendingFocusTurn(segmentTurns[0]?.number);
  }

  function handleExtend() {
    if (busy !== undefined) return;
    // 새 턴은 담은 채 연다(기본 상태가 담기다). 저장해야 고정 끝이 지금 방 끝으로 옮겨진다.
    edit(new Map([...baseStates, ...states]), { isExtended: true });
    setPendingFocusTurn(allTurns.find((turn) => turn.isNew)?.number);
  }

  function handleError(error: unknown, action: NovelAction) {
    const result = toNovelActionError(error, action);
    const recovery = toSelectionRecovery(error);
    if (recovery.resetEdits) setEdits(undefined);
    if (recovery.refetchSelection) void queryClient.invalidateQueries({ queryKey: novelKeys.sourceSelection(novel.id) });
    if (recovery.refetchMessages) void queryClient.invalidateQueries({ queryKey: chatRoomKeys.sourceMessages(roomId) });
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

  /** 지금 고른 것을 초안으로 저장한다. 담은 응답이 없으면 보내지 않고 이유를 말한다(서버가 같은 이유로 막는다). */
  async function saveDraft(): Promise<NovelSourceSelectionState | undefined> {
    if (fixedEndId === null || roomEndId === null) return undefined;
    if (!hasIncludedResponse(turns, states)) {
      setNotice({ tone: "error", message: "담을 대화를 하나 이상 골라주세요. AI 답이 든 턴이어야 해요." });
      return undefined;
    }
    const saved = await saveMutation.mutateAsync({
      novelId: novel.id,
      body: {
        baseRevision: edits?.baseRevision ?? base?.baseRevision ?? null,
        ...toSaveRoomEnd({ isExtended, isFixedEndMissing, fixedEndId, roomEndId }),
        sections: toSaveSections(turns, states),
      },
    });
    setEdits(undefined);
    return saved;
  }

  async function handleSave() {
    if (busy !== undefined) return;
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
      handleError(error, "saveSourceSelection");
    } finally {
      setBusy(undefined);
    }
  }

  async function handleApprove() {
    if (busy !== undefined) return;
    setNotice(undefined);
    setBusy("approve");
    let action: NovelAction = "saveSourceSelection";
    try {
      const current = needsSave ? await saveDraft() : state;
      if (current === undefined) return;
      const revision = current.draft?.revision;
      action = "approveSourceSelection";
      if (revision !== undefined && revision !== null) {
        await approveMutation.mutateAsync({ novelId: novel.id, revision });
      }
      setNotice({ tone: "done", message: "담을 대화를 승인했어요." });
      // 승인하면 저장·승인 버튼이 사라진다 — 누른 버튼과 함께 포커스가 떨어지지 않게 단계 제목으로 옮긴다.
      headingRef.current?.focus();
    } catch (error) {
      handleError(error, action);
    } finally {
      setBusy(undefined);
    }
  }

  if (base === undefined || fixedEndId === null) {
    return (
      <StepShell status={undefined} headingRef={headingRef}>
        <p className="text-sm break-keep text-muted-foreground">아직 대화가 없어요. 대화를 나눈 뒤 담을 대화를 고를 수 있어요.</p>
      </StepShell>
    );
  }

  const isApproveShown = status !== "approved" || needsSave;
  const isCollapsed = status === "approved" && !needsSave && !isFixedEndMissing && !isExpanded;
  return (
    <StepShell status={status} isSourceChanged={isSourceChanged} headingRef={headingRef}>
      {isCollapsed ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <p className="min-w-0 flex-1 text-sm text-muted-foreground tabular-nums">{toCountsLine(counts)}</p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              // 펼치면 이 버튼이 사라진다 — 포커스가 떨어지지 않게 단계 제목으로 먼저 옮긴다.
              headingRef.current?.focus();
              setIsExpanded(true);
            }}
          >
            담을 대화 고치기
          </Button>
        </div>
      ) : (
        <p id={helpId} className="text-sm break-keep text-muted-foreground">
          소설로 옮길 대화를 턴마다 골라요. 줄을 누르면 담기와 빼기가 바뀌고, Shift를 누른 채 누르면 앞에 누른 턴부터 이어서
          바뀌어요. 맥락으로 보낸 대화는 소설에 옮기지 않고 AI가 앞뒤 사정을 알도록 함께 읽어요.
        </p>
      )}
      {isSourceChanged && (
        <p className="rounded-lg border border-border px-3 py-2 text-sm break-keep text-foreground">
          고른 뒤 대화가 바뀐 턴이 있어요("고른 뒤 바뀜"). 확인한 뒤 저장하거나 승인하면 지금 대화로 다시 담겨요.
        </p>
      )}
      {isFixedEndMissing && (
        <p className="rounded-lg border border-border px-3 py-2 text-sm break-keep text-foreground">
          고른 때의 마지막 대화가 다시 쓰였거나 지워졌어요. 저장하면 지금 대화 끝까지를 고르는 범위로 삼아요. 담기·빼기를 확인한
          뒤 저장하거나 승인해주세요.
        </p>
      )}
      {state.hasNewMessages && !isExtended && newTurnCount > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-border px-3 py-2">
          <p className="min-w-0 flex-1 text-sm break-keep text-foreground">
            고른 뒤 이어진 대화가 {newTurnCount.toLocaleString()}턴 있어요. 저절로 담기지 않아요.
          </p>
          <Button type="button" variant="outline" size="sm" onClick={handleExtend}>
            새 구간 추가
          </Button>
        </div>
      )}
      {!isCollapsed && (
        <>
          <SourceTimeline
            turns={turns}
            states={states}
            changedKeys={changedKeys}
            expandedGapKeys={expandedGapKeys}
            foldableKeys={new Set(turns.filter((turn) => baseStates.get(turn.key) === "exclude").map((turn) => turn.key))}
            activeKey={anchorKey}
            onToggleTurn={handleToggleTurn}
            onSetGap={handleSetGap}
            onToggleGapExpanded={(gapTurns, isOpen) =>
              setExpandedGapKeys((prev) => {
                const next = new Set(prev);
                for (const turn of gapTurns) {
                  if (isOpen) next.add(turn.key);
                  else next.delete(turn.key);
                }
                return next;
              })
            }
          />
          <p aria-live="polite" aria-atomic className="text-sm text-muted-foreground tabular-nums">
            {toCountsLine(counts)}
          </p>
        </>
      )}
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
      {status === "approved" && !needsSave && !isCollapsed && (
        <p className="text-sm break-keep text-muted-foreground">승인한 선택이에요. 턴을 바꾸면 새 초안이 되고, 다시 승인해야 해요.</p>
      )}
      {(needsSave || isApproveShown) && (
        <div className="flex flex-wrap justify-end gap-2">
          {needsSave && (
            <Button
              type="button"
              variant="outline"
              aria-disabled={busy !== undefined}
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
              aria-disabled={busy !== undefined}
              className="aria-disabled:opacity-65"
              onClick={() => void handleApprove()}
            >
              {busy === "approve" && <Loader2 aria-hidden className="animate-spin" />}
              이대로 승인
            </Button>
          )}
        </div>
      )}
    </StepShell>
  );
}

type StepShellProps = {
  status: keyof typeof SOURCE_SELECTION_STATUS_LABEL | undefined;
  isSourceChanged?: boolean;
  headingRef?: RefObject<HTMLHeadingElement | null>;
  children: ReactNode;
};

/** 단계의 제목·상태 표시와 본문 자리. */
function StepShell({ status, isSourceChanged = false, headingRef, children }: StepShellProps) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {/* 승인 뒤 포커스를 받아 두는 자리라 `tabIndex=-1` 이고 포커스 테두리를 그리지 않는다. */}
        <h3 id={headingId} ref={headingRef} tabIndex={-1} className="text-lg font-semibold text-foreground outline-none">
          담을 대화
        </h3>
        {status !== undefined && (
          <span className="rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground">
            {SOURCE_SELECTION_STATUS_LABEL[status]}
          </span>
        )}
        {isSourceChanged && (
          <span className="rounded-full border border-border px-2 py-0.5 text-badge font-medium text-foreground">원문 바뀜</span>
        )}
      </div>
      {children}
    </section>
  );
}

/** 요약 줄 — 상태마다 턴 수. 이미 쓴 턴이 없으면 그 칸은 뺀다. */
function toCountsLine(counts: ReturnType<typeof countTurnStates>): string {
  return [
    `담기 ${counts.include.toLocaleString()}턴`,
    `맥락 ${counts.context.toLocaleString()}턴`,
    `빼기 ${counts.exclude.toLocaleString()}턴`,
    counts.locked > 0 ? `이미 씀 ${counts.locked.toLocaleString()}턴` : undefined,
  ]
    .filter((part) => part !== undefined)
    .join(" · ");
}

/** 그 턴의 줄로, 접힌 묶음 안이면 그 묶음의 버튼으로 포커스를 옮긴다. */
function focusTurn(number: number) {
  const row = document.querySelector(`[data-turn="${number}"]`);
  if (row instanceof HTMLElement) {
    row.focus();
    return;
  }
  for (const header of document.querySelectorAll<HTMLElement>("[data-segment-from]")) {
    const from = Number(header.dataset.segmentFrom);
    const to = Number(header.dataset.segmentTo);
    if (number >= from && number <= to) {
      header.querySelector<HTMLElement>("button:last-of-type")?.focus();
      return;
    }
  }
}
