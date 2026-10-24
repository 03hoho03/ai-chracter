import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { BookOpen, Loader2 } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { toast } from "sonner";

import { chatRoomKeys } from "@/entities/chat-room";
import { cloverKeys } from "@/entities/clover";
import {
  novelKeys,
  toNovelActionError,
  useApproveNovelEpisodeOutlineMutation,
  useNovelEpisodeOutlineQuery,
  useNovelOutlineQuery,
  useSaveNovelEpisodeOutlineMutation,
  type NovelAction,
  type NovelDetailResponse,
  type NovelEpisodeOutlineState,
  type NovelOutlineEpisode,
} from "@/entities/novel";

import { toEpisodeOutlineRecovery } from "../model/episodeRecovery";
import {
  isSameAsSceneView,
  moveScene,
  removeScene,
  toggleFlashback,
  toSaveScenes,
  toSceneDrafts,
  toSceneMoveBlockedReason,
  toSceneProblems,
  toSceneRemoveBlockedReason,
  updateSceneText,
  type SceneDraft,
} from "../model/episodeScenes";
import {
  MANUSCRIPT_STATUS_LABEL,
  SCENE_OUTLINE_STATUS_LABEL,
  toEpisodeOutlineBase,
  toManuscriptStatuses,
  toSceneMakeBlockedReason,
  toWriteBlockedReason,
  type ApprovedOutlineStatus,
  type ManuscriptStatus,
} from "../model/episodeStatus";
import { toTurnIndex, type OutlineTurn } from "../model/outlineEdits";
import { isEditBaseOutdated, toEpisodeOrdinals } from "../model/outlineStatus";

import type { OutlineTurnsStatus } from "./OutlineEpisodeItem";
import { SceneItem } from "./SceneItem";

/** 화 하나의 유료 작업(장면 구성안 만들기·원고 쓰기)과 그 상태. 작업 흐름은 다른 기능(화 만들기)에 있어 호출부가 이어 준다. */
export type EpisodeJobControl = {
  onMakeScenes: () => void;
  onWrite: () => void;
  /** 이 화의 확인·요청을 준비하는 중인가(버튼 아이콘이 진행 표시가 된다). */
  preparing: "episodeOutline" | "outlineChapter" | undefined;
  /** 화 작업이 도는 중이거나, 다른 버튼에서 시작한 준비가 진행 중인가 — 그동안 유료 버튼을 막는다. */
  isJobRunning: boolean;
  /** 이 화의 장면 구성안 작업이 도는 중인가(작업의 화를 모르면 참으로 둔다) — 끝나면 새 판이 오므로 그동안 고치지 않는다. */
  isSceneJobRunningHere: boolean;
  /** 이 화의 원고 작업이 도는 중인가. */
  isWriteJobRunningHere: boolean;
  isAiEditRunning: boolean;
  /** 작업 줄의 진행 문장 id. 작업이 도는 동안 못 누르는 버튼이 이 문장을 가리킨다. */
  statusId: string;
};

type NovelEpisodePlanStepProps = {
  novel: NovelDetailResponse;
  episodeKey: string;
  /** 담을 대화 단계와 같은 묶기로 만든 턴. 대화를 아직 못 받았으면 `undefined`. */
  turns: readonly OutlineTurn[] | undefined;
  isTurnsFailed: boolean;
  /** 화면 제목. 이 화면으로 옮기면 호출부가 여기로 포커스를 보낸다. */
  headingRef: RefObject<HTMLHeadingElement | null>;
  control: EpisodeJobControl;
  /** 원고가 된 화를 보드에서 고른다. */
  onOpenChapter: (chapterId: string) => void;
  onDraftDirtyChange: (isDirty: boolean) => void;
};

type Edits = { baseRevision: number; scenes: SceneDraft[] };

type StepNotice = { tone: "error" | "done"; message: string };

/**
 * 구성 3단계의 화 하나(`?select=plan:{화 키}`) — 그 화의 장면 구성안과 원고. 장면 구성안은 유료로 만들고(모델·금액 확인), 장면마다 글을
 * 고치고 차례를 바꾸고 빼고 회상 표시를 바꾼 뒤 "초안 저장"·"이대로 승인"으로 서버에 보낸다(둘 다 무료). 승인한 장면 구성안으로 원고를
 * 쓴다(유료) — 원고는 구성안 맨 앞 화부터 차례로만 쓴다.
 *
 * 원래 대화방이 지워졌으면 보기와 승인만 된다(서버가 만들기·저장·원고를 막는다). 원고가 된 화는 장면 구성안을 바꾸지 않는다 — 다시
 * 쓰려면 화 패널의 다시 만들기를 쓴다.
 */
export function NovelEpisodePlanStep(props: NovelEpisodePlanStepProps) {
  const { novel, episodeKey, headingRef } = props;
  const queryClient = useQueryClient();
  const outlineQuery = useNovelOutlineQuery(novel.id, { enabled: true });
  const approved = outlineQuery.data?.approved ?? undefined;
  const index = approved === undefined || approved === null ? -1 : approved.episodes.findIndex((item) => item.key === episodeKey);
  const episode = approved === undefined || approved === null ? undefined : approved.episodes[index];
  const episodeQuery = useNovelEpisodeOutlineQuery(novel.id, episodeKey, { enabled: episode !== undefined });
  const error = episodeQuery.error ?? outlineQuery.error;

  // 스위치를 막 껐으면 가격을 다시 받아 구성 화면을 거둔다.
  useEffect(() => {
    if (error === null || toEpisodeOutlineRecovery(error).refetchPricing === false) return;
    toast("지금은 구성 흐름을 쓸 수 없어요.");
    void queryClient.invalidateQueries({ queryKey: cloverKeys.pricing() });
  }, [error]);

  if (outlineQuery.data === undefined) {
    return (
      <EpisodeShell headingRef={headingRef} title="화">
        {outlineQuery.isError ? <LoadFailed onRetry={() => void outlineQuery.refetch()} isRetrying={outlineQuery.isFetching} /> : <Loading />}
      </EpisodeShell>
    );
  }
  if (approved === undefined || approved === null || episode === undefined) {
    return (
      <EpisodeShell headingRef={headingRef} title="이 화를 찾을 수 없어요">
        <p className="text-sm break-keep text-muted-foreground">
          이 화가 지금 승인한 전체 구성안에 없어요. 구성으로 돌아가 화를 다시 골라주세요.
        </p>
      </EpisodeShell>
    );
  }

  const ordinal = toEpisodeOrdinals(approved.episodes, novel.chapters)[index] ?? index + 1;
  const manuscript = toManuscriptStatuses(approved.episodes)[index] ?? { kind: "waiting" };
  const title = `${ordinal}화 · ${episode.title.trim() === "" ? "제목 없음" : episode.title}`;
  return (
    <EpisodeShell
      headingRef={headingRef}
      title={title}
      header={<EpisodeSummary episode={episode} sceneOutline={episode.sceneOutline} manuscript={manuscript} />}
    >
      {episodeQuery.data === undefined && episodeQuery.isError && (
        <LoadFailed onRetry={() => void episodeQuery.refetch()} isRetrying={episodeQuery.isFetching} />
      )}
      {episodeQuery.data === undefined && !episodeQuery.isError && <Loading />}
      {episodeQuery.data !== undefined && (
        <EpisodeEditor
          {...props}
          state={episodeQuery.data}
          ordinal={ordinal}
          episode={episode}
          manuscript={manuscript}
          outlineStatus={approved.stale ? "stale" : "ok"}
        />
      )}
    </EpisodeShell>
  );
}

type EpisodeEditorProps = NovelEpisodePlanStepProps & {
  state: NovelEpisodeOutlineState;
  ordinal: number;
  episode: NovelOutlineEpisode;
  manuscript: ManuscriptStatus;
  outlineStatus: ApprovedOutlineStatus;
};

function EpisodeEditor({
  novel,
  episodeKey,
  turns,
  isTurnsFailed,
  control,
  onOpenChapter,
  onDraftDirtyChange,
  state,
  ordinal,
  episode,
  manuscript,
  outlineStatus,
}: EpisodeEditorProps) {
  const queryClient = useQueryClient();
  const saveMutation = useSaveNovelEpisodeOutlineMutation();
  const approveMutation = useApproveNovelEpisodeOutlineMutation();
  const scenesHeadingRef = useRef<HTMLHeadingElement>(null);
  const makeReasonId = useId();
  const writeReasonId = useId();
  const [edits, setEdits] = useState<Edits | undefined>(undefined);
  const [editingId, setEditingId] = useState<string | undefined>(undefined);
  const [notice, setNotice] = useState<StepNotice | undefined>(undefined);
  const [busy, setBusy] = useState<"save" | "approve" | undefined>(undefined);
  // 구조를 바꾼 뒤 포커스를 둘 자리(선택자). 바뀐 목록이 그려진 뒤 옮긴다.
  const [pendingFocus, setPendingFocus] = useState<string | undefined>(undefined);

  const base = toEpisodeOutlineBase(state);
  const isRoomGone = novel.chatRoomId === null;
  const writtenChapterId = state.chapterId ?? episode.chapterId;
  const isWritten = writtenChapterId !== null;
  const turnIndex = useMemo(() => (turns === undefined ? undefined : toTurnIndex(turns)), [turns]);
  const turnsStatus = toTurnsStatus({ isRoomGone, isReady: turnIndex !== undefined, isFailed: isTurnsFailed });
  const scenes = edits?.scenes ?? (base === undefined ? [] : toSceneDrafts(base.view));
  const isDirty = base !== undefined && edits !== undefined && !isSameAsSceneView(edits.scenes, base.view);
  const isFormOpen = editingId !== undefined;
  const titleMaxLength = novel.limits.chapterTitleMaxLength;
  const canEdit =
    base !== undefined &&
    !base.isStale &&
    !isWritten &&
    !isRoomGone &&
    outlineStatus === "ok" &&
    !control.isSceneJobRunningHere &&
    busy === undefined;

  useEffect(() => {
    onDraftDirtyChange(isDirty || isFormOpen);
  }, [isDirty, isFormOpen]);
  useEffect(() => () => onDraftDirtyChange(false), []);

  // 고치는 사이 새 판이 왔다(장면 구성안 작업의 다시 시도·다른 탭) — 옛 판 위의 고침은 저장해도 409 로 버려지므로 지금 버리고 알린다.
  const latestRevision = base?.view.revision;
  useEffect(() => {
    // 저장·승인 중에는 이 화면이 낸 새 판이다 — 저장이 끝나며 고침을 비운다.
    if (busy !== undefined || !isEditBaseOutdated(edits?.baseRevision, latestRevision)) return;
    setEdits(undefined);
    setEditingId(undefined);
    setNotice({ tone: "error", message: "그사이 새 장면 구성안이 와서 고치던 것은 버렸어요. 새 장면 구성안을 확인해주세요." });
  }, [latestRevision]);

  useEffect(() => {
    if (pendingFocus === undefined) return;
    setPendingFocus(undefined);
    const target = document.querySelector(pendingFocus);
    if (target instanceof HTMLElement) target.focus();
    else scenesHeadingRef.current?.focus();
  }, [pendingFocus]);

  const makeBlockedReason = toSceneMakeBlockedReason({
    isRoomGone,
    isJobRunning: control.isJobRunning,
    isAiEditRunning: control.isAiEditRunning,
    outline: outlineStatus,
    isWritten,
    isDirty: isDirty || isFormOpen,
  });
  const isMakeBlocked = makeBlockedReason !== undefined || control.preparing !== undefined;
  const writeBlockedReason =
    manuscript.kind === "written"
      ? undefined
      : toWriteBlockedReason({
          isRoomGone,
          isJobRunning: control.isJobRunning,
          isAiEditRunning: control.isAiEditRunning,
          outline: outlineStatus,
          order: manuscript.kind,
          hasApproved: state.approved !== null,
          hasNewerDraft: state.draft !== null,
          isApprovedStale: state.approved?.stale === true,
          isDirty: isDirty || isFormOpen,
        });
  const isWriteBlocked = writeBlockedReason !== undefined || control.preparing !== undefined;

  function edit(next: SceneDraft[]) {
    if (base === undefined) return;
    setNotice(undefined);
    setEdits({ baseRevision: edits?.baseRevision ?? base.view.revision, scenes: next });
  }

  function handleError(error: unknown, action: NovelAction) {
    const result = toNovelActionError(error, action);
    const recovery = toEpisodeOutlineRecovery(error);
    if (recovery.resetEdits) {
      setEdits(undefined);
      setEditingId(undefined);
    }
    if (recovery.refetchEpisode) void queryClient.invalidateQueries({ queryKey: novelKeys.episodeOutline(novel.id, episodeKey) });
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

  /** 고친 장면 구성안을 새 초안으로 저장한다. 고칠 것이 남았으면 보내지 않고 그 문장을 보인다(서버가 같은 이유로 막는다). */
  async function saveDraft(): Promise<NovelEpisodeOutlineState | undefined> {
    if (edits === undefined) return state;
    const problems = toSceneProblems(edits.scenes, { titleMaxLength });
    if (problems.length > 0) {
      setNotice({ tone: "error", message: problems.join(" ") });
      return undefined;
    }
    const saved = await saveMutation.mutateAsync({
      novelId: novel.id,
      episodeKey,
      body: { baseRevision: edits.baseRevision, scenes: toSaveScenes(edits.scenes) },
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
        setNotice({ tone: "done", message: "초안을 저장했어요. 승인하면 원고를 쓸 수 있어요." });
        // 저장하면 고친 것이 없어져 누른 "초안 저장"이 사라진다 — 포커스가 떨어지지 않게 단계 제목으로 옮긴다.
        scenesHeadingRef.current?.focus();
      }
    } catch (error) {
      handleError(error, "saveEpisodeOutline");
    } finally {
      setBusy(undefined);
    }
  }

  async function handleApprove() {
    if (busy !== undefined || isFormOpen) return;
    setNotice(undefined);
    setBusy("approve");
    let action: NovelAction = "saveEpisodeOutline";
    try {
      const current = isDirty ? await saveDraft() : state;
      if (current === undefined) return;
      action = "approveEpisodeOutline";
      const revision = current.draft?.revision;
      if (revision !== undefined) await approveMutation.mutateAsync({ novelId: novel.id, episodeKey, revision });
      setNotice({
        tone: "done",
        message: manuscript.kind === "next" ? "장면 구성안을 승인했어요. 이제 원고를 쓸 수 있어요." : "장면 구성안을 승인했어요.",
      });
      // 승인하면 저장·승인 버튼이 사라진다 — 누른 버튼과 함께 포커스가 떨어지지 않게 단계 제목으로 옮긴다.
      scenesHeadingRef.current?.focus();
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
    setNotice(undefined);
    scenesHeadingRef.current?.focus();
  }

  const isApproveShown = base !== undefined && !base.isStale && !isWritten && (base.status !== "approved" || isDirty);
  const isActionBusy = busy !== undefined || isFormOpen;

  return (
    <>
      <section aria-labelledby={`${makeReasonId}-scenes`} className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          {/* 저장·승인 뒤 포커스를 받아 두는 자리라 `tabIndex=-1` 이고 포커스 테두리를 그리지 않는다. */}
          <h3
            id={`${makeReasonId}-scenes`}
            ref={scenesHeadingRef}
            tabIndex={-1}
            className="text-lg font-semibold text-foreground outline-none"
          >
            장면 구성안
          </h3>
          {base !== undefined && <OutlineBadge label={base.status === "draft" ? "초안" : "승인됨"} />}
          {base?.isStale === true && <OutlineBadge label="낡음" isActionable />}
        </div>

        {isWritten && (
          <p className="text-sm break-keep text-muted-foreground">
            원고를 쓴 화는 장면 구성안을 바꾸지 않아요. 다시 쓰려면 그 화 패널의 다시 만들기를 써요.
          </p>
        )}
        {isRoomGone && !isWritten && (
          <p className="text-sm break-keep text-muted-foreground">
            원래 대화방이 지워져 장면 구성안을 새로 만들거나 고칠 수 없어요. 지금 장면 구성안을 보고 승인할 수는 있어요.
          </p>
        )}
        {control.isSceneJobRunningHere && (
          <RunningLine>장면 구성안을 만들고 있어요. 끝나면 새 초안이 여기 와요.</RunningLine>
        )}

        {base === undefined ? (
          <>
            <p className="text-sm break-keep text-muted-foreground">
              이 화의 근거 대화를 장면으로 나눠요. 장면마다 제목·내용·목적·등장인물과 근거 대화가 붙고, 고친 뒤 승인하면 원고를 쓸 수 있어요.
            </p>
            <PaidButton
              label="장면 구성안 만들기"
              variant="secondary"
              isPreparing={control.preparing === "episodeOutline"}
              isBlocked={isMakeBlocked}
              blockedReason={makeBlockedReason}
              reasonId={makeReasonId}
              statusId={control.isJobRunning ? control.statusId : undefined}
              onClick={control.onMakeScenes}
            />
          </>
        ) : (
          <>
            {base.isStale && (
              <div className="flex flex-col gap-3 rounded-lg border border-border px-4 py-3">
                <p className="text-sm break-keep text-foreground">
                  전체 구성안에서 이 화의 근거가 바뀌어 장면 구성안이 낡았어요. 낡은 장면 구성안은 고치거나 승인하거나 원고에 쓸 수 없어요.
                  다시 만들어주세요.
                </p>
                {!isWritten && (
                  <PaidButton
                    label="다시 만들기"
                    variant="outline"
                    isPreparing={control.preparing === "episodeOutline"}
                    isBlocked={isMakeBlocked}
                    blockedReason={makeBlockedReason}
                    reasonId={makeReasonId}
                    statusId={control.isJobRunning ? control.statusId : undefined}
                    onClick={control.onMakeScenes}
                  />
                )}
              </div>
            )}
            <ol aria-label={`${ordinal}화 장면`} className="flex flex-col gap-3">
              {scenes.map((scene, index) => (
                <SceneItem
                  key={scene.localId}
                  scene={scene}
                  number={index + 1}
                  turnIndex={turnIndex}
                  turnsStatus={turnsStatus}
                  canEdit={canEdit && (editingId === undefined || editingId === scene.localId)}
                  isEditing={editingId === scene.localId}
                  moveBlockedReasons={{
                    up: toSceneMoveBlockedReason(scenes, scene.localId, -1),
                    down: toSceneMoveBlockedReason(scenes, scene.localId, 1),
                  }}
                  removeBlockedReason={toSceneRemoveBlockedReason(scenes)}
                  titleMaxLength={titleMaxLength}
                  onEdit={() => setEditingId(scene.localId)}
                  onApply={(text) => {
                    edit(updateSceneText(scenes, scene.localId, text));
                    setEditingId(undefined);
                    setPendingFocus(`[data-scene-edit="${scene.localId}"]`);
                  }}
                  onCancelEdit={() => {
                    setEditingId(undefined);
                    setPendingFocus(`[data-scene-edit="${scene.localId}"]`);
                  }}
                  onMove={(delta) => {
                    edit(moveScene(scenes, scene.localId, delta));
                    setPendingFocus(`[data-scene-menu="${scene.localId}"]`);
                  }}
                  onToggleFlashback={() => {
                    edit(toggleFlashback(scenes, scene.localId));
                    setPendingFocus(`[data-scene-menu="${scene.localId}"]`);
                  }}
                  onRemove={() => {
                    const next = removeScene(scenes, scene.localId);
                    const neighbor = next[Math.min(index, next.length - 1)];
                    edit(next);
                    // 뺀 장면의 메뉴가 사라진다 — 그 자리에 온 이웃 장면의 메뉴로 포커스를 옮긴다.
                    if (neighbor !== undefined) setPendingFocus(`[data-scene-menu="${neighbor.localId}"]`);
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
            {base.status === "approved" && !isDirty && !base.isStale && !isWritten && (
              <p className="text-sm break-keep text-muted-foreground">
                승인한 장면 구성안이에요. 고치면 새 초안이 되고, 다시 승인해야 원고에 쓰여요.
              </p>
            )}
            {isFormOpen && (
              <p className="text-sm break-keep text-muted-foreground">고치던 장면을 적용하거나 취소한 뒤 저장할 수 있어요.</p>
            )}

            <div className="flex flex-wrap items-center gap-2">
              {!base.isStale && !isWritten && (
                <PaidButton
                  label="다시 만들기"
                  variant="ghost"
                  isPreparing={control.preparing === "episodeOutline"}
                  isBlocked={isMakeBlocked}
                  blockedReason={makeBlockedReason}
                  reasonId={makeReasonId}
                  statusId={control.isJobRunning ? control.statusId : undefined}
                  onClick={control.onMakeScenes}
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
                    aria-disabled={isActionBusy || control.isSceneJobRunningHere}
                    className="aria-disabled:opacity-65"
                    onClick={() => {
                      if (control.isSceneJobRunningHere) return;
                      void handleApprove();
                    }}
                  >
                    {busy === "approve" && <Loader2 aria-hidden className="animate-spin" />}
                    이대로 승인
                  </Button>
                )}
              </div>
            </div>
          </>
        )}
      </section>

      <section aria-labelledby={`${writeReasonId}-heading`} className="flex flex-col gap-3 border-t border-border pt-6">
        <h3 id={`${writeReasonId}-heading`} className="text-lg font-semibold text-foreground">
          원고
        </h3>
        {writtenChapterId !== null ? (
          <div className="flex flex-col items-start gap-2">
            <p className="text-sm break-keep text-muted-foreground">이 화의 원고를 썼어요.</p>
            <Button type="button" variant="outline" size="sm" onClick={() => onOpenChapter(writtenChapterId)}>
              <BookOpen aria-hidden />
              {ordinal}화 보기
            </Button>
          </div>
        ) : (
          <>
            <p className="text-sm break-keep text-muted-foreground">
              승인한 장면 구성안대로 이 화의 원고를 써요. 다 쓰면 보드에 새 화로 놓여요.
            </p>
            {control.isWriteJobRunningHere && (
              <RunningLine>원고를 쓰고 있어요. 다 쓰면 보드의 새 화로 옮겨 가요.</RunningLine>
            )}
            <PaidButton
              label="원고 쓰기"
              variant="secondary"
              isPreparing={control.preparing === "outlineChapter"}
              isBlocked={isWriteBlocked}
              blockedReason={writeBlockedReason}
              reasonId={writeReasonId}
              statusId={control.isJobRunning ? control.statusId : undefined}
              onClick={control.onWrite}
            />
          </>
        )}
      </section>
    </>
  );
}

function toTurnsStatus(status: { isRoomGone: boolean; isReady: boolean; isFailed: boolean }): OutlineTurnsStatus {
  if (status.isRoomGone) return "gone";
  if (status.isReady) return "ready";
  return status.isFailed ? "error" : "loading";
}

/** 화 화면의 제목 자리와 본문. 제목은 이 화면으로 옮겼을 때 포커스를 받는 자리라 `tabIndex=-1` 이고 포커스 테두리를 그리지 않는다. */
function EpisodeShell({
  headingRef,
  title,
  header,
  children,
}: {
  headingRef: RefObject<HTMLHeadingElement | null>;
  title: string;
  /** 제목 바로 아래 붙는 화의 상태·줄거리. */
  header?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-3">
        <h2 ref={headingRef} tabIndex={-1} className="text-xl font-semibold tracking-tight break-keep text-foreground outline-none">
          {title}
        </h2>
        {header}
      </div>
      {children}
    </div>
  );
}

function EpisodeSummary({
  episode,
  sceneOutline,
  manuscript,
}: {
  episode: NovelOutlineEpisode;
  sceneOutline: NovelOutlineEpisode["sceneOutline"];
  manuscript: ManuscriptStatus;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-1.5">
        <OutlineBadge label={SCENE_OUTLINE_STATUS_LABEL[sceneOutline]} isActionable={sceneOutline === "stale"} />
        <OutlineBadge label={MANUSCRIPT_STATUS_LABEL[manuscript.kind]} isActionable={manuscript.kind === "next"} />
      </div>
      <p className="text-sm whitespace-pre-line text-pretty break-keep text-foreground">{episode.summary}</p>
      {episode.goal.trim() !== "" && (
        <p className="text-sm whitespace-pre-line break-keep text-muted-foreground">
          <span className="font-medium text-foreground">목표</span> · {episode.goal}
        </p>
      )}
    </div>
  );
}

function OutlineBadge({ label, isActionable = false }: { label: string; isActionable?: boolean }) {
  return (
    <span
      className={cn(
        "rounded-full border border-border px-2 py-0.5 text-badge font-medium",
        isActionable ? "text-foreground" : "text-muted-foreground",
      )}
    >
      {label}
    </span>
  );
}

function RunningLine({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-center gap-2 text-sm break-keep text-muted-foreground">
      <Loader2 aria-hidden className="size-4 shrink-0 animate-spin" />
      {children}
    </p>
  );
}

function Loading() {
  return (
    <div role="status" className="flex flex-col gap-2">
      <span className="sr-only">장면 구성안을 불러오는 중이에요.</span>
      <div aria-hidden className="h-24 animate-pulse rounded-xl bg-muted" />
      <div aria-hidden className="h-24 animate-pulse rounded-xl bg-muted" />
    </div>
  );
}

function LoadFailed({ onRetry, isRetrying }: { onRetry: () => void; isRetrying: boolean }) {
  return (
    <div className="flex flex-col items-start gap-3">
      <p className="text-sm break-keep text-muted-foreground">장면 구성안을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-disabled={isRetrying}
        className="aria-disabled:opacity-65"
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

type PaidButtonProps = {
  label: string;
  variant: "secondary" | "outline" | "ghost";
  isPreparing: boolean;
  isBlocked: boolean;
  blockedReason: string | undefined;
  reasonId: string;
  /** 작업이 도는 동안 함께 가리킬 작업 줄의 진행 문장 id. */
  statusId: string | undefined;
  onClick: () => void;
};

/** 유료 버튼(누르면 모델·금액 확인이 뜬다). 못 누르는 동안에도 `aria-disabled` 로 남기고 이유 한 줄을 단다. 작업이 도는 동안의 이유는
 * 작업 줄의 진행 문장을 함께 가리킨다. */
function PaidButton({ label, variant, isPreparing, isBlocked, blockedReason, reasonId, statusId, onClick }: PaidButtonProps) {
  const describedBy = [blockedReason === undefined ? undefined : reasonId, statusId].filter((id) => id !== undefined).join(" ");
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
          onClick();
        }}
      >
        {isPreparing && <Loader2 aria-hidden className="animate-spin" />}
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
