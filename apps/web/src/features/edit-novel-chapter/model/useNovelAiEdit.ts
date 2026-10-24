import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";

import { cloverKeys } from "@/entities/clover";
import {
  hasNovelErrorCode,
  hasNovelJobPollError,
  isNovelJobGone,
  isTerminalNovelJobStatus,
  novelKeys,
  toNovelActionError,
  toNovelJobFailureMessage,
  toPendingBlockEdits,
  toStalePatchIds,
  useNovelJobQuery,
  withStalePatches,
  type NovelAction,
  type NovelDetailResponse,
  type NovelJobResponse,
  type NovelPendingAiEdit,
} from "@/entities/novel";

import { useApplyAiEditMutation } from "../api/useApplyAiEditMutation";
import { useDismissAiEditMutation } from "../api/useDismissAiEditMutation";
import { useApplyPatchUnitMutation, useDismissPatchUnitMutation } from "../api/usePatchUnitMutations";
import { useRecheckBundleMutation } from "../api/useRecheckBundleMutation";
import { useStartAiEditMutation } from "../api/useStartAiEditMutation";
import { useStartBlockEditMutation } from "../api/useStartBlockEditMutation";
import { AiEditInstructionModal } from "../ui/AiEditInstructionModal";

import { toAiEditOutcome, toBlockEditArrivedMessage } from "./aiEditOutcome";
import { countFreshPatches, type PatchUnitView } from "./blockEditPatches";
import { formatParagraphIndexes, toBlockSelectionLabel, withObjectParticle } from "./blockSelection";
import { toChapterNotice, type ChapterNotice, type ChapterNoticeEvent } from "./chapterNotice";
import { formatParagraphRange, type ParagraphRange } from "./paragraphRange";

/** 금액 확인. 이 기능 밖의 확인 모달을 호출부가 넣어 준다(기능끼리 서로 가져다 쓰지 않는다). */
export type ConfirmAiEditSpend = (props: {
  title: string;
  description: string;
  cost: number;
  confirmLabel: string;
}) => Promise<boolean>;


type TrackedJob = { jobId: string; chapterId: string };

/** 고르기를 시작할 때 화면이 아는 장의 모습. 기준 개정은 **보고 있는 본문**의 개정이다 — 문단 인덱스가 그 본문을
 * 기준으로 하기 때문이다. */
export type AiEditTarget = {
  chapterId: string;
  chapterOrdinal: number;
  revisionId: string;
  paragraphs: readonly string[];
  range: ParagraphRange;
};

/** 여러 문단 고르기로 맡길 때 화면이 아는 장의 모습. 블록 id 와 문단 인덱스는 같은 차례(본문 차례)다. */
export type BlockEditTarget = {
  chapterId: string;
  chapterOrdinal: number;
  revisionId: string;
  paragraphs: readonly string[];
  blockIds: readonly string[];
  indexes: readonly number[];
};

type UseNovelAiEditOptions = {
  novel: NovelDetailResponse;
  confirmSpend: ConfirmAiEditSpend;
  /** 장 만들기·다시 만들기가 진행 중이거나 준비 중인가(상세에 진행 중 작업이 실리기 전의 틈까지). 소설 하나에
   * 진행 중 작업은 하나뿐이라 그동안 AI 수정을 미리 막는다. */
  isChapterJobBusy: boolean;
};

/** AI 수정의 흐름 전체: 지시 입력 → 금액 확인 → 작업(202) → 끝날 때까지 폴링 → 수정안을 적용하거나 버린다.
 *
 * 수정안은 서버가 들고 있다(소설 상세의 미적용 수정안). 그래서 화면은 작업이 성공하면 상세를 다시 받기만 하고,
 * 미리보기는 언제나 상세에서 그린다 — 새로고침·다른 기기에서 돌아와도 같은 수정안이 같은 자리에 다시 보인다.
 *
 * 지켜보는 작업은 둘 중 하나다 — 상세의 진행 중 작업(AI 수정일 때), 아니면 이 화면에서 방금 만든 작업. 그래서
 * 새로고침해도 폴링이 이어진다. 상태는 소설 하나에 묶이고, 다른 소설로 옮기면 호출부가 `key` 로 새로 마운트한다. */
export function useNovelAiEdit({ novel, confirmSpend, isChapterJobBusy }: UseNovelAiEditOptions) {
  const queryClient = useQueryClient();
  const statusId = useId();
  const [tracked, setTracked] = useState<TrackedJob | undefined>(undefined);
  const [isPreparing, setIsPreparing] = useState(false);
  // 장 머리 아래의 결과 문장. 일이 끝난 **그 순간**에 기록하고 다음 동작에서만 지운다 — 쿼리 상태에서 파생하면
  // 상세를 다시 받는 순간(진행 중 작업·수정안이 바뀌는 순간) 안내도 함께 사라진다. AI 수정 말고 같은 장의 직접
  // 고치기·되돌리기 결과도 `report` 로 여기 남긴다 — 문장이 한 줄이어야 지난 결과가 다음 동작 뒤에 남지 않는다.
  const [notice, setNotice] = useState<ChapterNotice | undefined>(undefined);
  // 안내를 바꾸는 동작마다 하나씩 오른다. 늦게 끝나는 안내(여러 문단 수정안 수 세기)가 그사이의 새 안내를 덮지 않게 한다.
  const noticeSeqRef = useRef(0);
  // 적용·버리기 중인 수정안(옛 수정안은 작업 id, 여러 문단 수정안은 단위 열쇠). 어느 쪽이든 한 번에 하나만 처리한다.
  const [actingEditId, setActingEditId] = useState<string | undefined>(undefined);
  // 마지막으로 적은 지시. 금액 확인에서 물렀거나 작업이 실패하면 다음에 지시 칸을 이 값으로 연다 — 환불된 작업은
  // 서버가 지시문을 지우므로 다시 채울 곳이 여기뿐이다.
  const [lastInstruction, setLastInstruction] = useState("");
  const startMutation = useStartAiEditMutation();
  const applyMutation = useApplyAiEditMutation();
  const dismissMutation = useDismissAiEditMutation();
  const startBlocksMutation = useStartBlockEditMutation();
  const applyPatchMutation = useApplyPatchUnitMutation();
  const dismissPatchMutation = useDismissPatchUnitMutation();
  const recheckMutation = useRecheckBundleMutation();

  const activeAiEdit: TrackedJob | undefined =
    novel.activeJob?.kind === "ai_edit" && novel.activeJob.chapterId !== null
      ? { jobId: novel.activeJob.id, chapterId: novel.activeJob.chapterId }
      : undefined;
  const watched = activeAiEdit ?? tracked;

  // 상세가 알려 온 진행 중 작업(새로고침·다른 기기에서 이어받은 것)도 이 화면이 지켜보는 작업으로 잡아 둔다. 상세가
  // 작업 폴링보다 먼저 끝난 모습을 받으면 진행 중 작업이 사라지는데, 그때 잡아 둔 것이 없으면 작업을 더 묻지 않아
  // 끝난 순간의 처리(실패·환불 안내, 잔액 갱신)가 돌지 않는다. 잡아 두면 그 작업 id 로 한 번 더 물어 끝을 받는다.
  useEffect(() => {
    if (activeAiEdit === undefined || activeAiEdit.jobId === tracked?.jobId) return;
    setTracked(activeAiEdit);
    // 잡을 시점은 상세가 새 작업을 알려 온 순간이다.
  }, [activeAiEdit?.jobId]);
  const jobQuery = useNovelJobQuery(novel.id, watched?.jobId);
  const job = jobQuery.data;
  const hasPollError = hasNovelJobPollError(jobQuery);
  // 작업이 없어졌다는 404 는 다시 물어도 같다(폴링도 멈춘다) — 진행 중으로 남겨 두면 버튼이 영영 잠긴다.
  const isJobGone = isNovelJobGone(jobQuery);
  const isRunning = watched !== undefined && !isTerminalNovelJobStatus(job?.status) && !isJobGone;
  const runningChapterOrdinal = novel.chapters.find((chapter) => chapter.id === watched?.chapterId)?.ordinal;
  const isOtherJobRunning = isChapterJobBusy || (novel.activeJob !== null && novel.activeJob.kind !== "ai_edit");
  const isBlocked = isPreparing || isRunning || isOtherJobRunning;

  // 이 화면이 아직 떠 있나. 지시 모달은 루트에 마운트돼 라우트가 바뀌어도 남고, 기다리던 응답은 화면을 떠난 뒤에도
  // 돌아온다 — 각 기다림 뒤에 이 값을 보고, 떠났으면 과금 요청을 보내지 않는다(진행·결과를 알릴 화면이 없다). 떠나는
  // 순간 지시 모달도 닫는다. 금액 확인 모달은 호출부가 넣어 준 것이라 호출부가 닫는다.
  const isMountedRef = useRef(false);
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      AiEditInstructionModal.end(null);
    };
  }, []);

  // 작업이 끝난 순간을 한 번만 처리한다.
  const settledJobIdsRef = useRef(new Set<string>());
  useEffect(() => {
    if (!job || !isTerminalNovelJobStatus(job.status) || settledJobIdsRef.current.has(job.id)) return;
    settledJobIdsRef.current.add(job.id);
    settleJob(job);
    // `settleJob` 은 렌더마다 새로 만들어지는 이 훅 안의 함수라 넣지 않는다 — 처리 시점은 `job` 이 정한다.
  }, [job]);

  useEffect(() => {
    if (!isJobGone || watched === undefined || settledJobIdsRef.current.has(watched.jobId)) return;
    settledJobIdsRef.current.add(watched.jobId);
    setNotice({ tone: "error", message: "AI 수정 작업을 찾을 수 없어요. 소설을 다시 불러왔어요." });
    void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
    // 처리 시점은 404 를 받은 순간 하나다.
  }, [isJobGone]);

  function settleJob(finished: NovelJobResponse) {
    // 실패는 환불이라 잔액·내역이 바뀌었다. 상세는 어느 쪽이든 낡았다(진행 중 작업이 끝났고, 성공이면 수정안이 생겼다).
    void queryClient.invalidateQueries({ queryKey: cloverKeys.all });
    void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });

    if (finished.status === "failed") {
      setNotice({ tone: "error", message: toNovelJobFailureMessage(finished) });
      return;
    }
    const outcome = toAiEditOutcome(finished);
    if (outcome.kind === "patches") {
      setLastInstruction("");
      // 수정안은 상세에 블록마다 실린다 — 다시 받은 상세에서 그 작업의 쓸 수 있는 수정안을 세어 알린다. 위에서 건 다시 받기를
      // 기다린다(새로 보내지 않는다). 받지 못했으면 수를 말하지 않는다 — 옛 상세로 세면 "없어요"라고 틀리게 말한다. 기다리는
      // 사이 다른 일이 안내를 바꿨으면 덮지 않는다.
      const ordinal = novel.chapters.find((chapter) => chapter.id === finished.chapterId)?.ordinal;
      const seq = noticeSeqRef.current;
      void queryClient
        .refetchQueries({ queryKey: novelKeys.detail(novel.id), exact: true }, { throwOnError: true, cancelRefetch: false })
        .then(
          () => {
            const detail = queryClient.getQueryData<NovelDetailResponse>(novelKeys.detail(novel.id));
            const edit = detail === undefined ? undefined : toPendingBlockEdits(detail).find((item) => item.id === finished.id);
            return edit === undefined ? 0 : countFreshPatches(edit);
          },
          () => undefined,
        )
        .then((freshCount) => {
          if (noticeSeqRef.current !== seq) return;
          setNotice({ tone: "info", message: toBlockEditArrivedMessage(ordinal, freshCount) });
        });
      return;
    }
    if (outcome.kind === "unavailable") {
      setNotice({ tone: "info", message: outcome.message });
      return;
    }
    setLastInstruction("");
    const ordinal = novel.chapters.find((chapter) => chapter.id === finished.chapterId)?.ordinal;
    setNotice({
      tone: "info",
      message: `${ordinal === undefined ? "" : `${ordinal}화 `}수정안이 왔어요. 고른 문단 아래에서 적용하거나 버릴 수 있어요.`,
    });
  }

  function report(event: ChapterNoticeEvent) {
    noticeSeqRef.current += 1;
    setNotice(toChapterNotice(event));
  }

  function handleRequestError(error: unknown, action: NovelAction) {
    const result = toNovelActionError(error, action);
    if (result === null) return;
    report({ type: "rejected", message: result.message });
    // 여러 문단 수정 스위치가 꺼졌다 — 가격을 다시 받아 고르기를 거둔다.
    if (hasNovelErrorCode(error, "NOVEL_MULTI_BLOCK_EDIT_DISABLED")) {
      void queryClient.invalidateQueries({ queryKey: cloverKeys.pricing() });
    }
    // 낡아 거절된 수정안은 다시 받기 전에도 적용 버튼을 거둔다.
    const stalePatchIds = toStalePatchIds(error);
    if (stalePatchIds.length > 0) {
      queryClient.setQueryData<NovelDetailResponse>(novelKeys.detail(novel.id), (detail) =>
        detail === undefined ? undefined : { ...detail, pendingBlockEdits: withStalePatches(detail.pendingBlockEdits, stalePatchIds) },
      );
    }
    if (result.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
  }

  /** 지시를 받고 금액을 확인받아 작업을 만든다. 작업을 만들었으면 `true` — 호출부가 고른 범위를 푼다. */
  async function start(target: AiEditTarget): Promise<boolean> {
    if (isBlocked) return false;
    report({ type: "started" });
    setIsPreparing(true);
    try {
      const rangeLabel = formatParagraphRange(target.range);
      const instruction = await AiEditInstructionModal.call({
        rangeLabel,
        paragraphs: target.paragraphs.slice(target.range.start, target.range.end + 1),
        maxLength: novel.limits.aiEditInstructionMaxLength,
        defaultInstruction: lastInstruction,
      });
      if (instruction === null || !isMountedRef.current) return false;
      setLastInstruction(instruction);
      const cost = novel.prices.aiEdit;
      const isConfirmed = await confirmSpend({
        title: `${target.chapterOrdinal}화 ${rangeLabel}을 AI로 고칠까요?`,
        description:
          "적은 대로 고친 수정안을 만들어요. 수정안은 적용하기 전까지 본문을 바꾸지 않아요. 마음에 들지 않아 버려도 쓴 클로버는 돌려드리지 않아요.",
        cost,
        confirmLabel: "AI로 고치기",
      });
      if (!isConfirmed || !isMountedRef.current) return false;
      const started = await startMutation.mutateAsync({
        novelId: novel.id,
        chapterId: target.chapterId,
        baseRevisionId: target.revisionId,
        paragraphStart: target.range.start,
        paragraphEnd: target.range.end,
        instruction,
        expectedCost: cost,
      });
      setTracked({ jobId: started.id, chapterId: target.chapterId });
      return true;
    } catch (error) {
      handleRequestError(error, "aiEdit");
      return false;
    } finally {
      setIsPreparing(false);
    }
  }

  /** 고른 블록들(같은 장면)을 지시대로 고친 수정안을 맡긴다 — 지시 → 금액 확인 → 작업. 작업을 만들었으면 `true`. 스위치가
   * 켜져 있을 때만 화면이 부른다(꺼짐이면 서버가 404 다). 연속 범위로 골랐어도 이 길 하나로 보낸다. */
  async function startBlocks(target: BlockEditTarget): Promise<boolean> {
    if (isBlocked) return false;
    report({ type: "started" });
    setIsPreparing(true);
    try {
      const label = toBlockSelectionLabel(target.indexes);
      const instruction = await AiEditInstructionModal.call({
        rangeLabel: label,
        paragraphs: target.indexes.map((index) => target.paragraphs[index] ?? ""),
        paragraphLabels: target.indexes.map((index) => formatParagraphIndexes([index])),
        hasKindChips: true,
        maxLength: novel.limits.aiEditInstructionMaxLength,
        defaultInstruction: lastInstruction,
      });
      if (instruction === null || !isMountedRef.current) return false;
      setLastInstruction(instruction);
      const cost = novel.prices.aiEdit;
      const isConfirmed = await confirmSpend({
        title: `${target.chapterOrdinal}화 ${withObjectParticle(label)} AI로 고칠까요?`,
        description:
          "적은 대로 고른 문단마다 수정안을 만들어요. 수정안은 적용하기 전까지 본문을 바꾸지 않아요. 마음에 들지 않아 버려도 쓴 클로버는 돌려드리지 않아요.",
        cost,
        confirmLabel: "AI로 고치기",
      });
      if (!isConfirmed || !isMountedRef.current) return false;
      const started = await startBlocksMutation.mutateAsync({
        novelId: novel.id,
        chapterId: target.chapterId,
        baseRevisionId: target.revisionId,
        blockIds: [...target.blockIds],
        instruction,
        expectedCost: cost,
      });
      setTracked({ jobId: started.id, chapterId: target.chapterId });
      return true;
    } catch (error) {
      handleRequestError(error, "aiEdit");
      return false;
    } finally {
      setIsPreparing(false);
    }
  }

  /** 적용 단위(독립 수정안 하나·묶음 하나)를 적용한다. */
  async function applyPatchUnit(unit: PatchUnitView, chapterOrdinal: number) {
    if (actingEditId !== undefined) return;
    report({ type: "started" });
    setActingEditId(unit.key);
    try {
      await applyPatchMutation.mutateAsync({
        novelId: novel.id,
        jobId: unit.jobId,
        unit: unit.request,
        patchIds: unit.patchIds,
      });
      report({ type: "patchesApplied", chapterOrdinal, count: unit.patchIds.length });
    } catch (error) {
      handleRequestError(error, "applyPatch");
    } finally {
      setActingEditId(undefined);
    }
  }

  /** 적용 단위 하나를 버리거나(`unit`), 한 작업의 남은 수정안을 모두 버린다(`jobId` 만). */
  async function dismissPatches(
    target: { unit: PatchUnitView } | { jobId: string; remainingCount: number },
    chapterOrdinal: number,
  ) {
    if (actingEditId !== undefined) return;
    report({ type: "started" });
    const isUnit = "unit" in target;
    setActingEditId(isUnit ? target.unit.key : `${target.jobId}:all`);
    try {
      await dismissPatchMutation.mutateAsync(
        isUnit
          ? { novelId: novel.id, jobId: target.unit.jobId, unit: target.unit.request, patchIds: target.unit.patchIds }
          : { novelId: novel.id, jobId: target.jobId, unit: "all", patchIds: "all" },
      );
      report({
        type: "patchesDismissed",
        chapterOrdinal,
        count: isUnit ? target.unit.patchIds.length : target.remainingCount,
      });
    } catch (error) {
      handleRequestError(error, "dismissPatch");
    } finally {
      setActingEditId(undefined);
    }
  }

  /** 묶음을 다시 검사한다(무료). 따로 적용해도 된다는 판정이면 `true` — 그 묶음이 다시 받은 상세에서 풀려 누른 버튼이 사라지므로
   * 호출부가 포커스를 옮긴다. 아니라는 판정이나 실패면 버튼이 그 자리에 남는다. 적용·버리기와 같은 줄을 서 한 번에 하나만 보낸다. */
  async function recheckBundle(unit: PatchUnitView, chapterOrdinal: number): Promise<boolean> {
    if (actingEditId !== undefined || !("bundleId" in unit.request)) return false;
    report({ type: "started" });
    setActingEditId(toRecheckKey(unit));
    try {
      const verdict = await recheckMutation.mutateAsync({
        novelId: novel.id,
        jobId: unit.jobId,
        bundleId: unit.request.bundleId,
      });
      report({ type: "bundleRechecked", chapterOrdinal, separable: verdict.separable, reason: verdict.reason });
      return verdict.separable;
    } catch (error) {
      handleRequestError(error, "recheckBundle");
      return false;
    } finally {
      setActingEditId(undefined);
    }
  }

  async function apply(edit: NovelPendingAiEdit, chapterOrdinal: number) {
    if (actingEditId !== undefined) return;
    report({ type: "started" });
    setActingEditId(edit.id);
    try {
      await applyMutation.mutateAsync({ novelId: novel.id, jobId: edit.id });
      report({ type: "applied", chapterOrdinal });
    } catch (error) {
      handleRequestError(error, "applyAiEdit");
    } finally {
      setActingEditId(undefined);
    }
  }

  async function dismiss(edit: NovelPendingAiEdit, chapterOrdinal: number) {
    if (actingEditId !== undefined) return;
    report({ type: "started" });
    setActingEditId(edit.id);
    try {
      await dismissMutation.mutateAsync({ novelId: novel.id, jobId: edit.id });
      report({ type: "dismissed", chapterOrdinal });
    } catch (error) {
      handleRequestError(error, "dismissAiEdit");
    } finally {
      setActingEditId(undefined);
    }
  }

  return {
    statusId,
    isPreparing,
    isRunning,
    isBlocked,
    isOtherJobRunning,
    hasPollError,
    runningChapterOrdinal,
    notice,
    actingEditId,
    start,
    startBlocks,
    apply,
    dismiss,
    applyPatchUnit,
    dismissPatches,
    recheckBundle,
    report,
  };
}

/** 다시 검사 중인 묶음을 가리키는 `actingEditId` — 같은 묶음의 적용·버리기 열쇠와 갈라 어느 버튼이 진행 중인지 보인다. */
export function toRecheckKey(unit: PatchUnitView): string {
  return `${unit.key}:recheck`;
}

export type NovelAiEditFlow = ReturnType<typeof useNovelAiEdit>;
