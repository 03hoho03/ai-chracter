import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";

import { cloverKeys, useCloverPricingQuery } from "@/entities/clover";
import {
  hasNovelJobPollError,
  isNovelJobGone,
  isProtagonistNameRequiredError,
  hasNovelErrorCode,
  isTerminalNovelJobStatus,
  novelEpisodeOutlineQueryOptions,
  novelKeys,
  novelOutlineQueryOptions,
  toBatchRangeLabel,
  toNovelActionError,
  toNovelJobFailureMessage,
  toOutlineModelOptions,
  toProposalModelOptions,
  toRegenerateModelOptions,
  useNovelJobQuery,
  chaptersInBatch,
  initialChapterModelId,
  isNovelIllustrationsOn,
  isOutlineFlowChapter,
  hasPendingEdits,
  type NovelAction,
  type NovelChapterModelId,
  type NovelChapterSummary,
  type NovelDetailResponse,
  type NovelJobResponse,
  type PricedChapterModelOption,
} from "@/entities/novel";
import { assertNever } from "@/shared/lib/assertNever";

import { useChapterProposalMutation } from "../api/useChapterProposalMutation";
import { useCreateChainMutation } from "../api/useCreateChainMutation";
import { useCreateChapterMutation } from "../api/useCreateChapterMutation";
import { useCreateOutlineMutation } from "../api/useCreateOutlineMutation";
import {
  useCreateEpisodeOutlineMutation,
  useCreateOutlineChapterMutation,
  useRegenerateOutlineChapterMutation,
} from "../api/useOutlineEpisodeJobMutations";
import { useRegenerateChapterMutation } from "../api/useRegenerateChapterMutation";
import { ChapterBoundaryModal } from "../ui/ChapterBoundaryModal";
import { ProtagonistNameModal } from "../ui/ProtagonistNameModal";

import { toChainProgress } from "./chainProgress";
import { OUTLINE_SPEND_FOOTNOTE, toDoneMessage, toJobEpisodeKey, toRetryTarget, type RetryTarget } from "./chapterJobOutcome";
import { toOutlineFlowAvailability } from "./regenerateAction";
import { toRegenerateConfirmDescription } from "./regenerateConfirm";
import { toEpisodeJobRefusal } from "./episodeJobGuard";

/** 화 다시 만들기·전체 구성안 만들기의 금액 확인. 이 기능 밖의 확인 모달을 호출부가 넣어 준다(기능끼리 서로 가져다 쓰지 않는다).
 * 소설 상위 모델 허용이 있으면 모달이 모델도 고르게 하므로, 확정하면 고른 모델과 이용자가 본 금액을 돌려준다.
 * 그만두면 `null` 이다. */
export type ConfirmChapterSpend = (props: {
  title: string;
  description: string;
  confirmLabel: string;
  /** 고를 수 있는 모델과 그 모델의 금액 — 상세의 묶음 다시 만들기 목록 그대로다. */
  options: PricedChapterModelOption[];
  initialModelId: NovelChapterModelId;
  /** 금액 줄 아래 한 줄 — 돌려받는 조건처럼 금액에 붙는 말. */
  footnote?: string;
}) => Promise<{ model: NovelChapterModelId; cost: number } | null>;

/** 이 흐름이 지켜보는 작업 — AI 수정을 뺀 전부다. 남은 대화 한 번에(연쇄)는 경계 고르기의 한 칸으로 시작한다. */
type ChapterJobKind = Exclude<NovelJobResponse["kind"], "ai_edit">;

/** `episodeKey` 는 장면 구성안·원고 작업의 화 키다 — 작업 응답·상세의 진행 중 작업이 싣고, 비면(옛 작업) 이 화면이 시작하며 기억한
 * 키, 그것도 없으면 `null` 이다. */
type TrackedJob = {
  jobId: string;
  kind: ChapterJobKind;
  chapterId: string | null;
  batchId: string | null;
  episodeKey: string | null;
};

/** 작업을 만들기 전 단계(이름·제안·고르기·확인·요청)를 어느 버튼에서 시작했나. */
type PreparingKind = "create" | "regenerate" | "outline" | "episodeOutline" | "outlineChapter";

/** 화면에 남겨 두는 결과 문장. 작업이 끝나거나 요청이 거절된 **그 순간**에 기록하고 다음 동작에서만 지운다 —
 * 쿼리 상태에서 그때그때 파생하면 상세를 다시 받는 순간(진행 중 작업이 사라지는 순간) 안내도 함께 사라진다. */
export type ChapterJobNotice =
  | { tone: "error"; message: string; retry?: RetryTarget }
  | { tone: "done"; message: string };

type UseNovelChapterJobOptions = {
  novel: NovelDetailResponse;
  confirmSpend: ConfirmChapterSpend;
  /** 작업이 성공해 그 장이 상세에 실린 뒤 부른다 — 화면이 그 장으로 옮기고 제목에 포커스를 둔다.
   * `isRegenerated` 는 있던 장을 다시 만들었는가다(그 장의 본문이 통째로 바뀌었다). */
  onChapterReady: (chapter: NovelChapterSummary, chapters: NovelChapterSummary[], isRegenerated: boolean) => void;
};

/** 장 만들기·다시 만들기의 흐름 전체: 주인공 이름 → (만들기) 경계 제안·끝 턴 고르기 / (다시 만들기) 금액 확인 →
 * 작업 생성(202) → 끝날 때까지 폴링 → 결과.
 *
 * 지켜보는 작업은 둘 중 하나다 — 이 화면에서 방금 만든 작업, 아니면 상세의 `activeJob`(새로고침·다른 기기에서 돌아온
 * 경우). 그래서 새로고침해도 폴링이 이어진다. 소설 하나에 진행 중 작업은 하나뿐이라(서버가 409 로 막는다) 지켜볼
 * 작업도 하나다. AI 수정 작업은 여기서 지켜보지 않고 버튼만 잠근다.
 *
 * 이 훅의 상태는 소설 하나에 묶인다 — 다른 소설로 옮겨 가면 호출부가 `key` 로 새로 마운트한다. */
export function useNovelChapterJob({ novel, confirmSpend, onChapterReady }: UseNovelChapterJobOptions) {
  const queryClient = useQueryClient();
  const statusId = useId();
  const [tracked, setTracked] = useState<TrackedJob | undefined>(undefined);
  // 작업을 만들기 전 단계(이름·제안·고르기·확인·요청)가 진행 중인가, 그렇다면 어느 버튼에서 시작했나.
  const [preparing, setPreparing] = useState<PreparingKind | undefined>(undefined);
  // 장면 구성안·원고를 준비하는 화 키 — 그 화 화면의 버튼만 진행 표시를 단다.
  const [preparingEpisodeKey, setPreparingEpisodeKey] = useState<string | undefined>(undefined);
  const [notice, setNotice] = useState<ChapterJobNotice | undefined>(undefined);
  const proposalMutation = useChapterProposalMutation();
  const createMutation = useCreateChapterMutation();
  const chainMutation = useCreateChainMutation();
  const regenerateMutation = useRegenerateChapterMutation();
  const outlineMutation = useCreateOutlineMutation();
  const episodeOutlineMutation = useCreateEpisodeOutlineMutation();
  const outlineChapterMutation = useCreateOutlineChapterMutation();
  const outlineRegenerateMutation = useRegenerateOutlineChapterMutation();
  // 이 화면이 시작한 장면 구성안·원고 작업의 화 키. 작업 응답에 화 키가 없는 옛 작업의 다시 시도를 그 화로 잇는 데 쓴다.
  const episodeKeyByJobIdRef = useRef(new Map<string, string>());
  // 장면 구성안을 고치는 중인 화 키 — 화 화면이 알려 준다. 작업 줄의 다시 시도는 그 화면의 막기를 거치지 않아 여기서 본다.
  const editingEpisodeKeysRef = useRef(new Set<string>());
  // 소설 만들기 거절의 문장이 노벨 정책 스위치에 따라 다르다(`toNovelizeForbiddenCopy`).
  const pricing = useCloverPricingQuery().data;
  const isPolicyV2Enabled = pricing?.novelPublicPolicyV2Enabled === true;
  // 다시 만들면 붙인 삽화가 자리를 잃는다는 문장은 삽화를 쓸 수 있을 때만 확인 화면에 싣는다.
  const isIllustrationsOn = isNovelIllustrationsOn(pricing);
  // 구성안으로 쓴 화의 다시 만들기는 구성 흐름 스위치 뒤에 있다. 가격을 받는 중이면 아직 모른다.
  const outlineFlow = toOutlineFlowAvailability(pricing);

  const activeChapterJob: TrackedJob | undefined =
    novel.activeJob && novel.activeJob.kind !== "ai_edit"
      ? {
          jobId: novel.activeJob.id,
          kind: novel.activeJob.kind,
          chapterId: novel.activeJob.chapterId,
          batchId: novel.activeJob.batchId,
          episodeKey: toJobEpisodeKey(novel.activeJob, episodeKeyByJobIdRef.current.get(novel.activeJob.id)),
        }
      : undefined;
  // 서버가 진행 중이라고 알려 온 작업이 먼저다 — 이 화면이 지켜보던 작업이 끝난 뒤 다른 탭이 새 작업을 시작했으면
  // 그쪽을 지켜봐야 버튼이 다시 잠긴다. 202 직후 상세를 다시 받기 전에는 방금 만든 작업을 지켜본다.
  const watched = activeChapterJob ?? tracked;
  const jobQuery = useNovelJobQuery(novel.id, watched?.jobId);
  const job = jobQuery.data;
  const hasPollError = hasNovelJobPollError(jobQuery);
  // 작업이 없어졌다는 404 는 다시 물어도 같다(폴링도 멈춘다) — 진행 중으로 남겨 두면 버튼이 영영 잠긴다.
  const isJobGone = isNovelJobGone(jobQuery);
  const isJobRunning = watched !== undefined && !isTerminalNovelJobStatus(job?.status) && !isJobGone;
  const isAiEditRunning = novel.activeJob?.kind === "ai_edit";
  const isRoomGone = novel.chatRoomId === null;
  const isBusy = preparing !== undefined || isJobRunning || isAiEditRunning;
  // 다시 만드는 중인 화들의 이름(`3~5화`). 작업이 가리키는 묶음이 상세에 없으면(낡은 상세) 이름 없이 말한다.
  const runningRangeLabel =
    watched?.batchId === null || watched?.batchId === undefined ? undefined : toBatchRangeLabel(novel.chapters, watched.batchId);
  // 남은 대화 한 번에의 진행(만든 묶음 / 만들 묶음). 부모 작업 응답이 먼저이고, 첫 응답 전에는 상세의 진행 중 작업이다.
  const chainProgress =
    isJobRunning && watched?.kind === "chain_generate"
      ? toChainProgress(job ?? novel.activeJob)
      : undefined;

  // 이 화면이 아직 떠 있나. 흐름의 모달은 루트에 마운트돼 라우트가 바뀌어도 남고, 기다리던 응답은 화면을 떠난 뒤에도
  // 돌아온다 — 각 기다림 뒤에 이 값을 보고, 떠났으면 과금 요청도 화면 이동도 하지 않는다(진행·결과를 알릴 화면이
  // 없고, 다른 소설로 옮긴 뒤라면 보이지 않는 소설에 장이 생긴다). 떠나는 순간 이 흐름이 연 모달도 닫는다 — 페이지
  // 위에 남은 모달에서 확정해도 위 확인이 요청을 막지만, 누를 수 있는데 아무 일도 없는 버튼을 남기지 않는다. 금액
  // 확인 모달은 호출부가 넣어 준 것이라 호출부가 닫는다.
  const isMountedRef = useRef(false);
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      ProtagonistNameModal.end(false);
      ChapterBoundaryModal.end(null);
    };
  }, []);

  // 작업이 끝난 순간을 한 번만 처리한다. 같은 작업을 두 번 처리하면 이동·포커스가 되풀이된다.
  const settledJobIdsRef = useRef(new Set<string>());
  useEffect(() => {
    if (!job || !isTerminalNovelJobStatus(job.status) || settledJobIdsRef.current.has(job.id)) return;
    settledJobIdsRef.current.add(job.id);
    void settleJob(job);
    // `settleJob` 은 렌더마다 새로 만들어지는 이 훅 안의 함수라 의존성에 넣지 않는다 — 처리 시점은 `job` 이 정한다.
  }, [job]);

  // 연쇄는 묶음 하나가 끝날 때마다 새 화가 생긴다 — 끝까지 기다리지 않고 목차·인물을 그때그때 다시 받아, 보드와
  // 목차에 만든 화가 차례로 놓이게 한다. 끝난 순간의 정리는 `settleJob` 이 한다.
  const completedBatches = isJobRunning && watched?.kind === "chain_generate" ? job?.completedBatches : undefined;
  useEffect(() => {
    if (completedBatches === undefined || completedBatches === null || completedBatches === 0) return;
    void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
    void queryClient.invalidateQueries({ queryKey: novelKeys.characters(novel.id) });
    // 처리 시점은 만든 묶음 수가 바뀐 순간이다.
  }, [completedBatches]);

  useEffect(() => {
    if (!isJobGone || watched === undefined || settledJobIdsRef.current.has(watched.jobId)) return;
    settledJobIdsRef.current.add(watched.jobId);
    // 현실적인 경로는 다른 탭에서 소설을 지운 경우다 — 상세를 다시 받으면 화면이 「찾을 수 없어요」로 간다.
    setNotice({ tone: "error", message: "화 작업을 찾을 수 없어요. 소설을 다시 불러왔어요." });
    void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
    // 처리 시점은 404 를 받은 순간 하나다.
  }, [isJobGone]);

  async function settleJob(finished: NovelJobResponse) {
    // 성공은 차감 그대로, 실패는 환불이라 어느 쪽이든 잔액·내역이 바뀌었을 수 있다.
    void queryClient.invalidateQueries({ queryKey: cloverKeys.all });

    if (finished.status === "failed") {
      const retry = toRetryTarget(finished, {
        chapters: novel.chapters,
        episodeKey: episodeKeyByJobIdRef.current.get(finished.id) ?? null,
      });
      setNotice({ tone: "error", message: toNovelJobFailureMessage(finished), retry });
      void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
      // 고른 대화가 바뀌어 실패한 구성안·장면 구성안·원고는 담을 대화에 바뀐 턴 표시가 생기고, 구성안의 낡음 표시가 바뀔 수 있다.
      if (
        finished.kind === "outline_generate" ||
        finished.kind === "episode_outline_generate" ||
        finished.kind === "outline_chapter_generate"
      ) {
        invalidateOutlineFlow();
      }
      return;
    }

    // 상세(목차·진행 중 작업)·목록, 그리고 화 본문처럼 이 소설에 딸린 캐시는 전부 낡았다. 끝난 작업 자신은 더
    // 바뀌지 않으므로 다시 묻지 않는다. 상세를 받아 온 뒤에 이동해야 새 화가 목차에 있다.
    await queryClient.invalidateQueries({
      queryKey: novelKeys.all,
      predicate: (query) => query.queryKey[1] !== "job",
    });
    const fresh = queryClient.getQueryData<NovelDetailResponse>(novelKeys.detail(novel.id));
    // 기다리는 동안 이용자가 다른 화면으로 갔으면 소설 화면으로 끌고 오지 않는다.
    if (!isMountedRef.current) return;
    // 작업이 가리키는 화는 그 묶음의 첫 화다(화를 골라 들어온 옛 다시 만들기는 고른 화). 그 화로 옮긴다.
    const chapter = fresh?.chapters.find((item) => item.id === finished.chapterId);
    const isRegenerated = finished.kind === "chapter_regenerate";
    setNotice({ tone: "done", message: toDoneMessage(finished, fresh?.chapters ?? []) });
    if (fresh && chapter) onChapterReady(chapter, fresh.chapters, isRegenerated);
  }

  /** 구성 화면의 단계(담을 대화·전체 구성안·화별 장면 구성안)를 다시 받는다 — 구성 흐름 요청이 선택이나 구성안이 서버와 어긋났다는
   * 이유로 거절됐거나 그 때문에 실패했다. */
  function invalidateOutlineFlow() {
    void queryClient.invalidateQueries({ queryKey: novelKeys.sourceSelection(novel.id) });
    void queryClient.invalidateQueries({ queryKey: novelKeys.outline(novel.id) });
    void queryClient.invalidateQueries({ queryKey: novelKeys.episodeOutlineAll(novel.id) });
  }

  function handleRequestError(error: unknown, action: NovelAction) {
    const result = toNovelActionError(error, action, { isPolicyV2Enabled });
    if (action === "outlineRegenerate" && hasNovelErrorCode(error, "NOVEL_OUTLINE_FLOW_DISABLED")) {
      // 스위치가 꺼졌으면 가격을 다시 받아 그 화의 다시 만들기를 막는다.
      void queryClient.invalidateQueries({ queryKey: cloverKeys.pricing() });
    }
    if (action === "outline" || action === "episodeOutline" || action === "outlineChapter") {
      // 스위치가 꺼졌으면 가격을 다시 받아 구성 화면을 거둔다. 그 밖의 거절은 대개 담을 대화가 바뀐 것이라 두 단계를 다시 받는다.
      if (hasNovelErrorCode(error, "NOVEL_OUTLINE_FLOW_DISABLED")) void queryClient.invalidateQueries({ queryKey: cloverKeys.pricing() });
      else invalidateOutlineFlow();
    }
    if (result === null) return;
    setNotice({ tone: "error", message: result.message });
    if (result.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
  }

  /** 지금 캐시의 상세에 진행 중 작업이 있는가. 흐름을 시작할 때 받은 상세는 그 뒤에 시작된 AI 수정을 모를 수 있어,
   * 이용자에게 확인을 받기 직전에 한 번 더 본다. 작업이 있으면 흐름을 조용히 멈춘다 — 다시 그린 화면이 이미 그
   * 작업의 진행 줄과 못 누르는 사유를 보이고 있다.
   *
   * 캐시에 AI 수정이 실리는 때는 그 요청이 202 를 받고 상세를 다시 받은 **뒤**다. 요청이 날아가는 동안과 다시 받기
   * 전에는 이 확인도 그 작업을 보지 못한다. 그래서 효과는 확인이 그보다 늦을 때뿐이다 — 장 만들기는 제안 호출(수 초)
   * 을 기다린 뒤에 확인해 대개 늦다. 다시 만들기는 누르자마자 확인하므로 이 확인으로는 그 틈을 못 덮는다 — 장
   * 화면이 AI 수정을 준비·요청 중인 동안 다시 만들기 버튼을 따로 잠근다. 다른 탭에서 시작한 작업은 서버가 409 로
   * 막는다. */
  function hasActiveJobNow() {
    return (queryClient.getQueryData<NovelDetailResponse>(novelKeys.detail(novel.id))?.activeJob ?? null) !== null;
  }

  function askProtagonistName() {
    return ProtagonistNameModal.call({ novelId: novel.id, maxLength: novel.limits.protagonistNameMaxLength });
  }

  async function ensureProtagonistName() {
    if (novel.protagonistName?.trim()) return true;
    return askProtagonistName();
  }

  /** 상세의 이름이 낡아(다른 탭에서 비웠거나) 서버가 이름을 먼저 받으라고 하면, 이름을 받은 뒤 같은 요청을 한 번
   * 더 보낸다. 금액은 이미 확인받았으므로 다시 묻지 않는다. */
  async function requestJob(send: () => Promise<NovelJobResponse>): Promise<NovelJobResponse | undefined> {
    try {
      return await send();
    } catch (error) {
      if (!isProtagonistNameRequiredError(error)) throw error;
      if (!(await askProtagonistName()) || !isMountedRef.current) return undefined;
      return send();
    }
  }

  function track(started: NovelJobResponse, episodeKey: string | null = null) {
    if (started.kind === "ai_edit") return;
    if (episodeKey !== null) episodeKeyByJobIdRef.current.set(started.id, episodeKey);
    setTracked({
      jobId: started.id,
      kind: started.kind,
      chapterId: started.chapterId,
      batchId: started.batchId,
      episodeKey: toJobEpisodeKey(started, episodeKey),
    });
  }

  async function startCreate() {
    if (isBusy || isRoomGone) return;
    setNotice(undefined);
    setPreparing("create");
    let action: NovelAction = "proposal";
    try {
      if (!(await ensureProtagonistName()) || !isMountedRef.current) return;
      // 모델을 먼저 정하고 그 모델로 제안을 받는다 — 모델마다 담을 수 있는 턴 수가 달라 후보가 모델을 따라 바뀐다.
      // 처음에는 직전에 쓴 모델로 받고, 모달에서 모델을 바꾸면 모달이 다시 받는다.
      const modelOptions = toProposalModelOptions(novel.chapterModels ?? []);
      const initialModelId = initialChapterModelId(modelOptions, novel.lastChapterModel);
      const proposal = await proposalMutation.mutateAsync({ novelId: novel.id, model: initialModelId });
      if (!isMountedRef.current) return;
      if (proposal.candidates.length === 0) {
        setNotice({ tone: "error", message: "화로 묶을 새 대화가 없어요. 대화를 더 이어 간 뒤 만들어주세요." });
        return;
      }
      if (hasActiveJobNow()) return;
      const firstEpisodeOrdinal = Math.max(0, ...novel.chapters.map((chapter) => chapter.ordinal)) + 1;
      const choice = await ChapterBoundaryModal.call({
        novelId: novel.id,
        proposal,
        // 제안 응답의 목록이 그 순간의 허용이다. 없으면 상세의 목록으로 그린다.
        modelOptions: proposal.chapterModels === undefined ? modelOptions : toProposalModelOptions(proposal.chapterModels),
        initialModelId,
        firstEpisodeOrdinal,
      });
      if (choice === null || !isMountedRef.current) return;
      action = choice.kind === "chain" ? "chain" : "generate";
      const started = await requestJob(() =>
        choice.kind === "chain"
          ? chainMutation.mutateAsync({
              novelId: novel.id,
              model: choice.model,
              expectedCost: choice.cost,
              maxBatches: choice.maxBatches,
            })
          : createMutation.mutateAsync({
              novelId: novel.id,
              endMessageId: choice.endMessageId,
              expectedCost: choice.cost,
              model: choice.model,
            }),
      );
      if (started) track(started);
    } catch (error) {
      handleRequestError(error, action);
    } finally {
      setPreparing(undefined);
    }
  }

  /** 한 번에 만든 화들(묶음)을 함께 다시 만든다. 어느 화에서 눌러도 그 화가 든 묶음 전체다. 고를 수 있는 모델과
   * 금액은 상세의 그 묶음 목록이 정한다 — 맞지 않는 모델은 확인 화면에서 비활성 + 이유로 보인다. */
  async function startRegenerate(batchId: string) {
    if (isBusy || isRoomGone) return;
    setNotice(undefined);
    const batch = novel.batches.find((item) => item.id === batchId);
    const batchChapters = chaptersInBatch(novel.chapters, batchId);
    const rangeLabel = toBatchRangeLabel(novel.chapters, batchId);
    if (batch === undefined || rangeLabel === undefined) {
      // 상세가 낡았다(다른 탭에서 지웠다) — 다시 받으면 목차와 버튼이 맞아진다.
      setNotice({ tone: "error", message: "다시 만들 화를 찾을 수 없어요. 소설을 다시 불러왔어요." });
      void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
      return;
    }
    const options = toRegenerateModelOptions(batch.regenerateOptions);
    if (!options.some((option) => option.disabledReason === undefined)) {
      setNotice({ tone: "error", message: `${rangeLabel}는 지금 고를 수 있는 모델로 다시 만들 수 없어요.` });
      return;
    }
    setPreparing("regenerate");
    try {
      if (!(await ensureProtagonistName()) || !isMountedRef.current || hasActiveJobNow()) return;
      const batchChapterIds = new Set(batchChapters.map((chapter) => chapter.id));
      const choice = await confirmSpend({
        title: `${rangeLabel}를 다시 만들까요?`,
        description: toRegenerateConfirmDescription({
          rangeLabel,
          episodeCount: batchChapters.length,
          hasPendingAiEdits: hasPendingEdits(novel, batchChapterIds),
          isIllustrationsOn,
        }),
        confirmLabel: "다시 만들기",
        options,
        initialModelId: initialChapterModelId(options, novel.lastChapterModel),
      });
      if (choice === null || !isMountedRef.current) return;
      const started = await requestJob(() =>
        regenerateMutation.mutateAsync({
          novelId: novel.id,
          batchId,
          expectedCost: choice.cost,
          model: choice.model,
        }),
      );
      if (started) track(started);
    } catch (error) {
      handleRequestError(error, "regenerate");
    } finally {
      setPreparing(undefined);
    }
  }

  /** 지금 승인한 담을 대화로 전체 구성안을 만든다(유료). 모델과 금액은 확인 직전에 구성안 조회를 새로 받아 정한다 — 화면에
   * 떠 있던 값은 그사이 허용 모델·가격이 바뀌었을 수 있다. 승인하지 않은 구성안은 돌려주지 않고, 만들지 못하면 서버가 모두
   * 돌려준다(금액 줄 아래 한 줄로 알린다). */
  async function startOutline() {
    if (isBusy || isRoomGone) return;
    setNotice(undefined);
    setPreparing("outline");
    try {
      if (!(await ensureProtagonistName()) || !isMountedRef.current) return;
      const state = await queryClient.fetchQuery(novelOutlineQueryOptions(novel.id));
      if (!isMountedRef.current || hasActiveJobNow()) return;
      const options = toOutlineModelOptions(state.models);
      if (options.length === 0) {
        setNotice({ tone: "error", message: "지금 고를 수 있는 모델이 없어 구성안을 만들 수 없어요." });
        return;
      }
      const hasOutline = (state.draft ?? state.approved) !== null;
      const choice = await confirmSpend({
        title: hasOutline ? "전체 구성안을 다시 만들까요?" : "전체 구성안을 만들까요?",
        description: hasOutline
          ? "담은 대화로 구성안을 새로 만들어요. 새 구성안은 초안으로 오고, 고친 뒤 승인해야 다음 단계로 이어져요."
          : "담은 대화를 화로 나눈 구성안을 만들어요. 고친 뒤 승인해야 다음 단계로 이어져요.",
        confirmLabel: hasOutline ? "다시 만들기" : "구성안 만들기",
        options,
        initialModelId: initialChapterModelId(options, novel.lastChapterModel),
        footnote: OUTLINE_SPEND_FOOTNOTE,
      });
      if (choice === null || !isMountedRef.current) return;
      const started = await requestJob(() =>
        outlineMutation.mutateAsync({ novelId: novel.id, expectedCost: choice.cost, model: choice.model }),
      );
      if (started) track(started);
    } catch (error) {
      handleRequestError(error, "outline");
    } finally {
      setPreparing(undefined);
    }
  }

  /** 구성안으로 쓴 화 하나를 같은 장면 구성안으로 다시 쓴다(새 라우트). 고를 수 있는 모델과 금액은 상세의 그 화 묶음 다시 만들기 목록이
   * 정한다 — 구성안으로 쓴 화는 화 하나짜리 묶음이라 그 금액이 서버의 이 동작 금액과 같다. 옛 묶음 다시 만들기 라우트는 이 화를 거절한다. */
  async function startOutlineRegenerate(chapterId: string) {
    if (isBusy || isRoomGone || outlineFlow !== "on") return;
    setNotice(undefined);
    const chapter = novel.chapters.find((item) => item.id === chapterId);
    const batch = chapter === undefined ? undefined : novel.batches.find((item) => item.id === chapter.batchId);
    if (chapter === undefined || batch === undefined || !isOutlineFlowChapter(chapter)) {
      // 상세가 낡았다(다른 탭에서 지웠다) — 다시 받으면 목차와 버튼이 맞아진다.
      setNotice({ tone: "error", message: "다시 만들 화를 찾을 수 없어요. 소설을 다시 불러왔어요." });
      void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
      return;
    }
    const label = `${chapter.ordinal}화`;
    const options = toRegenerateModelOptions(batch.regenerateOptions);
    if (!options.some((option) => option.disabledReason === undefined)) {
      setNotice({ tone: "error", message: `${label}는 지금 고를 수 있는 모델로 다시 만들 수 없어요.` });
      return;
    }
    setPreparing("regenerate");
    try {
      if (!(await ensureProtagonistName()) || !isMountedRef.current || hasActiveJobNow()) return;
      const choice = await confirmSpend({
        title: `${label}를 다시 만들까요?`,
        description: toRegenerateConfirmDescription({
          rangeLabel: label,
          episodeCount: 1,
          hasPendingAiEdits: hasPendingEdits(novel, new Set([chapter.id])),
          isIllustrationsOn,
          isOutlineFlow: true,
        }),
        confirmLabel: "다시 만들기",
        options,
        initialModelId: initialChapterModelId(options, novel.lastChapterModel),
      });
      if (choice === null || !isMountedRef.current) return;
      const started = await requestJob(() =>
        outlineRegenerateMutation.mutateAsync({
          novelId: novel.id,
          chapterId: chapter.id,
          expectedCost: choice.cost,
          model: choice.model,
        }),
      );
      if (started) track(started);
    } catch (error) {
      handleRequestError(error, "outlineRegenerate");
    } finally {
      setPreparing(undefined);
    }
  }

  /** 승인한 전체 구성안의 한 화로 장면 구성안을 만든다(유료). 승인하지 않은 장면 구성안은 돌려주지 않고, 만들지 못하면 서버가 모두
   * 돌려준다(금액 줄 아래 한 줄로 알린다). */
  async function startEpisodeOutline(episodeKey: string) {
    await startEpisodeJob(episodeKey, "episodeOutline");
  }

  /** 그 화의 승인한 장면 구성안으로 원고를 쓴다(유료, 화 단가 하나). */
  async function startOutlineChapter(episodeKey: string) {
    await startEpisodeJob(episodeKey, "outlineChapter");
  }

  /** 장면 구성안·원고의 공통 흐름. 모델·금액은 확인 직전에 그 화의 장면 구성안 조회를 새로 받아 정한다(장면 구성안은 `models`, 원고는
   * `chapterModels`) — 화면에 떠 있던 값은 그사이 허용 모델·가격이 바뀌었을 수 있다. 확인 창이 어느 화의 일인지 말하도록 화 제목은 전체
   * 구성안 조회에서 읽는다(작업 줄의 다시 시도로 열면 화 화면 밖일 수 있다). */
  async function startEpisodeJob(episodeKey: string, kind: "episodeOutline" | "outlineChapter") {
    if (isBusy || isRoomGone) return;
    setNotice(undefined);
    setPreparing(kind);
    setPreparingEpisodeKey(episodeKey);
    try {
      if (!(await ensureProtagonistName()) || !isMountedRef.current) return;
      const [state, outline] = await Promise.all([
        queryClient.fetchQuery(novelEpisodeOutlineQueryOptions(novel.id, episodeKey)),
        queryClient.fetchQuery(novelOutlineQueryOptions(novel.id)),
      ]);
      if (!isMountedRef.current || hasActiveJobNow()) return;
      const refusal = toEpisodeJobRefusal(kind, state, editingEpisodeKeysRef.current.has(episodeKey));
      if (refusal !== undefined) {
        setNotice({ tone: "error", message: refusal });
        return;
      }
      const options = toOutlineModelOptions(kind === "episodeOutline" ? state.models : state.chapterModels);
      if (options.length === 0) {
        setNotice({ tone: "error", message: "지금 고를 수 있는 모델이 없어요." });
        return;
      }
      const title = outline.approved?.episodes.find((episode) => episode.key === episodeKey)?.title.trim();
      const named = title === undefined || title === "" ? "이 화" : `「${title}」 화`;
      const hasSceneOutline = (state.draft ?? state.approved) !== null;
      const initialModelId = initialChapterModelId(options, novel.lastChapterModel);
      const choice = await confirmSpend(
        kind === "episodeOutline"
          ? {
              title: hasSceneOutline ? "장면 구성안을 다시 만들까요?" : "장면 구성안을 만들까요?",
              description: hasSceneOutline
                ? `${named}의 장면 구성안을 새로 만들어요. 새 구성안은 초안으로 오고, 고친 뒤 승인해야 원고로 이어져요.`
                : `${named}의 근거 대화를 장면으로 나눈 구성안을 만들어요. 고친 뒤 승인해야 원고로 이어져요.`,
              confirmLabel: hasSceneOutline ? "다시 만들기" : "장면 구성안 만들기",
              options,
              initialModelId,
              footnote: OUTLINE_SPEND_FOOTNOTE,
            }
          : {
              title: "원고를 쓸까요?",
              description: `${named}를 승인한 장면 구성안대로 써요. 다 쓰면 보드에 새 화로 놓여요.`,
              confirmLabel: "원고 쓰기",
              options,
              initialModelId,
            },
      );
      if (choice === null || !isMountedRef.current) return;
      const mutation = kind === "episodeOutline" ? episodeOutlineMutation : outlineChapterMutation;
      const started = await requestJob(() =>
        mutation.mutateAsync({ novelId: novel.id, episodeKey, expectedCost: choice.cost, model: choice.model }),
      );
      if (started) track(started, episodeKey);
    } catch (error) {
      handleRequestError(error, kind);
    } finally {
      setPreparing(undefined);
      setPreparingEpisodeKey(undefined);
    }
  }

  /** 화 화면이 그 화의 장면 구성안을 고치는 중인지 알린다(저장하지 않은 고침이나 열린 고치기 폼). */
  function reportEpisodeEditing(episodeKey: string, isEditing: boolean) {
    if (isEditing) editingEpisodeKeysRef.current.add(episodeKey);
    else editingEpisodeKeysRef.current.delete(episodeKey);
  }

  function retry(target: RetryTarget) {
    switch (target.kind) {
      case "generate":
        void startCreate();
        return;
      case "regenerate":
        void startRegenerate(target.batchId);
        return;
      case "outlineRegenerate":
        void startOutlineRegenerate(target.chapterId);
        return;
      case "outline":
        void startOutline();
        return;
      case "episodeOutline":
        void startEpisodeOutline(target.episodeKey);
        return;
      case "outlineChapter":
        void startOutlineChapter(target.episodeKey);
        return;
      default:
        assertNever(target);
    }
  }

  return {
    statusId,
    preparing,
    isJobRunning,
    isAiEditRunning,
    isRoomGone,
    isBusy,
    hasPollError,
    runningKind: isJobRunning ? watched?.kind : undefined,
    /** 도는 장면 구성안·원고 작업의 화 키. 작업이 키를 싣지 않았고(옛 작업) 이 화면이 시작하지도 않았으면 모른다(`null`). */
    runningEpisodeKey: isJobRunning ? (watched?.episodeKey ?? null) : null,
    preparingEpisodeKey,
    outlineFlow,
    runningRangeLabel,
    chainProgress,
    notice,
    startCreate,
    startRegenerate,
    startOutline,
    startOutlineRegenerate,
    startEpisodeOutline,
    startOutlineChapter,
    reportEpisodeEditing,
    retry,
  };
}

export type NovelChapterJobFlow = ReturnType<typeof useNovelChapterJob>;
