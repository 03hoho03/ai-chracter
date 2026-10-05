import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";

import { cloverKeys } from "@/entities/clover";
import {
  hasNovelJobPollError,
  isNovelJobGone,
  isProtagonistNameRequiredError,
  isTerminalNovelJobStatus,
  novelKeys,
  toNovelActionError,
  toNovelJobFailureMessage,
  useNovelJobQuery,
  type NovelAction,
  type NovelChapterSummary,
  type NovelDetailResponse,
  type NovelJobResponse,
} from "@/entities/novel";

import { useChapterProposalMutation } from "../api/useChapterProposalMutation";
import { useCreateChapterMutation } from "../api/useCreateChapterMutation";
import { useRegenerateChapterMutation } from "../api/useRegenerateChapterMutation";
import { ChapterBoundaryModal } from "../ui/ChapterBoundaryModal";
import { ProtagonistNameModal } from "../ui/ProtagonistNameModal";

/** 금액 확인. 이 기능 밖의 확인 모달을 호출부가 넣어 준다(기능끼리 서로 가져다 쓰지 않는다). */
export type ConfirmNovelSpend = (props: {
  title: string;
  description: string;
  cost: number;
  confirmLabel: string;
}) => Promise<boolean>;

type ChapterJobKind = "chapter_generate" | "chapter_regenerate";

type TrackedJob = { jobId: string; kind: ChapterJobKind; chapterId: string | null };

type RetryTarget = { kind: "generate" } | { kind: "regenerate"; chapterId: string };

/** 화면에 남겨 두는 결과 문장. 작업이 끝나거나 요청이 거절된 **그 순간**에 기록하고 다음 동작에서만 지운다 —
 * 쿼리 상태에서 그때그때 파생하면 상세를 다시 받는 순간(진행 중 작업이 사라지는 순간) 안내도 함께 사라진다. */
export type ChapterJobNotice =
  | { tone: "error"; message: string; retry?: RetryTarget }
  | { tone: "done"; message: string };

type UseNovelChapterJobOptions = {
  novel: NovelDetailResponse;
  confirmSpend: ConfirmNovelSpend;
  /** 작업이 성공해 그 장이 상세에 실린 뒤 부른다 — 화면이 그 장으로 옮기고 제목에 포커스를 둔다. */
  onChapterReady: (chapter: NovelChapterSummary, chapters: NovelChapterSummary[]) => void;
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
  const [preparing, setPreparing] = useState<"create" | "regenerate" | undefined>(undefined);
  const [notice, setNotice] = useState<ChapterJobNotice | undefined>(undefined);
  const proposalMutation = useChapterProposalMutation();
  const createMutation = useCreateChapterMutation();
  const regenerateMutation = useRegenerateChapterMutation();

  const activeChapterJob: TrackedJob | undefined =
    novel.activeJob && novel.activeJob.kind !== "ai_edit"
      ? { jobId: novel.activeJob.id, kind: novel.activeJob.kind, chapterId: novel.activeJob.chapterId }
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
  const runningChapterOrdinal = novel.chapters.find((chapter) => chapter.id === watched?.chapterId)?.ordinal;

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

  useEffect(() => {
    if (!isJobGone || watched === undefined || settledJobIdsRef.current.has(watched.jobId)) return;
    settledJobIdsRef.current.add(watched.jobId);
    // 현실적인 경로는 다른 탭에서 소설을 지운 경우다 — 상세를 다시 받으면 화면이 「찾을 수 없어요」로 간다.
    setNotice({ tone: "error", message: "장 작업을 찾을 수 없어요. 소설을 다시 불러왔어요." });
    void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
    // 처리 시점은 404 를 받은 순간 하나다.
  }, [isJobGone]);

  async function settleJob(finished: NovelJobResponse) {
    // 성공은 차감 그대로, 실패는 환불이라 어느 쪽이든 잔액·내역이 바뀌었을 수 있다.
    void queryClient.invalidateQueries({ queryKey: cloverKeys.all });

    if (finished.status === "failed") {
      setNotice({ tone: "error", message: toNovelJobFailureMessage(finished), retry: toRetryTarget(finished) });
      void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
      return;
    }

    // 상세(목차·진행 중 작업)·목록, 그리고 장 본문처럼 이 소설에 딸린 캐시는 전부 낡았다. 끝난 작업 자신은 더
    // 바뀌지 않으므로 다시 묻지 않는다. 상세를 받아 온 뒤에 이동해야 새 장이 목차에 있다.
    await queryClient.invalidateQueries({
      queryKey: novelKeys.all,
      predicate: (query) => query.queryKey[1] !== "job",
    });
    const fresh = queryClient.getQueryData<NovelDetailResponse>(novelKeys.detail(novel.id));
    // 기다리는 동안 이용자가 다른 화면으로 갔으면 소설 화면으로 끌고 오지 않는다.
    if (!isMountedRef.current) return;
    const chapter = fresh?.chapters.find((item) => item.id === finished.chapterId);
    const verb = finished.kind === "chapter_regenerate" ? "다시 만들었어요" : "만들었어요";
    setNotice({ tone: "done", message: chapter ? `${chapter.ordinal}장을 ${verb}.` : `장을 ${verb}.` });
    if (fresh && chapter) onChapterReady(chapter, fresh.chapters);
  }

  function handleRequestError(error: unknown, action: NovelAction) {
    const result = toNovelActionError(error, action);
    if (result === null) return;
    setNotice({ tone: "error", message: result.message });
    if (result.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
  }

  /** 지금 캐시의 상세에 진행 중 작업이 있는가. 흐름을 시작할 때 받은 상세는 AI 수정이 막 시작된 것을 모를 수 있다
   * (AI 수정이 금액 확인 뒤 요청을 보내는 동안, 그리고 202 뒤 상세를 다시 받기 전). 그 틈에 시작한 흐름이 경계
   * 고르기·금액 확인을 다 거친 뒤에야 409 를 받지 않도록, 이용자에게 확인을 받기 직전에 한 번 더 본다. 작업이 있으면
   * 흐름을 조용히 멈춘다 — 다시 그린 화면이 이미 그 작업의 진행 줄과 못 누르는 사유를 보이고 있다. */
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

  function track(started: NovelJobResponse, kind: ChapterJobKind) {
    setTracked({ jobId: started.id, kind, chapterId: started.chapterId });
  }

  async function startCreate() {
    if (isBusy || isRoomGone) return;
    setNotice(undefined);
    setPreparing("create");
    let action: NovelAction = "proposal";
    try {
      if (!(await ensureProtagonistName()) || !isMountedRef.current) return;
      const proposal = await proposalMutation.mutateAsync(novel.id);
      if (!isMountedRef.current) return;
      if (proposal.candidates.length === 0) {
        setNotice({ tone: "error", message: "장으로 묶을 새 대화가 없어요. 대화를 더 이어 간 뒤 만들어주세요." });
        return;
      }
      if (hasActiveJobNow()) return;
      const chapterOrdinal = Math.max(0, ...novel.chapters.map((chapter) => chapter.ordinal)) + 1;
      const endMessageId = await ChapterBoundaryModal.call({ proposal, chapterOrdinal });
      if (endMessageId === null || !isMountedRef.current) return;
      action = "generate";
      const started = await requestJob(() =>
        createMutation.mutateAsync({ novelId: novel.id, endMessageId, expectedCost: proposal.cost }),
      );
      if (started) track(started, "chapter_generate");
    } catch (error) {
      handleRequestError(error, action);
    } finally {
      setPreparing(undefined);
    }
  }

  async function startRegenerate(chapter: Pick<NovelChapterSummary, "id" | "ordinal">) {
    if (isBusy || isRoomGone) return;
    setNotice(undefined);
    setPreparing("regenerate");
    try {
      if (!(await ensureProtagonistName()) || !isMountedRef.current || hasActiveJobNow()) return;
      const cost = novel.prices.chapterRegenerate;
      const isConfirmed = await confirmSpend({
        title: `${chapter.ordinal}장을 다시 만들까요?`,
        description: "같은 대화로 이 장을 새로 써요. 지금 글은 이력에 남아요.",
        cost,
        confirmLabel: "다시 만들기",
      });
      if (!isConfirmed || !isMountedRef.current) return;
      const started = await requestJob(() =>
        regenerateMutation.mutateAsync({ novelId: novel.id, chapterId: chapter.id, expectedCost: cost }),
      );
      if (started) track(started, "chapter_regenerate");
    } catch (error) {
      handleRequestError(error, "regenerate");
    } finally {
      setPreparing(undefined);
    }
  }

  function retry(target: RetryTarget) {
    if (target.kind === "generate") {
      void startCreate();
      return;
    }
    const chapter = novel.chapters.find((item) => item.id === target.chapterId);
    if (chapter) void startRegenerate(chapter);
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
    runningChapterOrdinal,
    notice,
    startCreate,
    startRegenerate,
    retry,
  };
}

export type NovelChapterJobFlow = ReturnType<typeof useNovelChapterJob>;

function toRetryTarget(job: NovelJobResponse): RetryTarget | undefined {
  // 원래 대화가 바뀌어 실패한 재생성은 다시 해도 같은 결과라 다시 시도를 내밀지 않는다.
  if (job.failureReason === "source_changed") return undefined;
  if (job.kind === "chapter_generate") return { kind: "generate" };
  if (job.kind === "chapter_regenerate" && job.chapterId !== null) return { kind: "regenerate", chapterId: job.chapterId };
  return undefined;
}
