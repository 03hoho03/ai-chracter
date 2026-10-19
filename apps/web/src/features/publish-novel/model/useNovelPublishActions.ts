import { useRef } from "react";

import { useCloverPricingQuery } from "@/entities/clover";
import { useNovelPublicationQuery, type NovelPublicationStatus } from "@/entities/novel";

import { usePublishNovelRun, type PublishRunResult } from "../api/usePublishNovelRun";
import { PublishNovelModal } from "../ui/PublishNovelModal";
import { WithdrawNovelPublicationModal } from "../ui/WithdrawNovelPublicationModal";
import { toCancelReviewOutcome, toPublishRange, toPublishRequests, type PublishChoice } from "./publicationView";

type PublishableNovel = { id: string; chapters: readonly { id: string; ordinal: number }[] };

/** 작품 정보의 공개 절과 편집 보드의 공개 버튼이 함께 쓰는 공개 동작 — 공개 상태 조회, 공개 모달을 열어 고른 범위를
 * 화 하나씩 보내기, 실패 뒤 같은 선택(범위·화별 가격·변경 요약)으로 다시 시도, 거두기·신청 취소 모달. 공개가 끝나면
 * 독자에게 열렸는지 승인 대기로 끝났는지를 돌려준다(`PublishRunResult`).
 *
 * 다시 시도가 고른 가격·요약을 잊으면 6화부터를 기본값(유료)으로, 고친 화를 요약 없이 보내게 된다 — 그래서 선택 전체를
 * 기억한다. 노벨 정책 스위치는 가격 응답이 말한다(값이 없으면 꺼짐). */
export function useNovelPublishActions(novel: PublishableNovel) {
  const publication = useNovelPublicationQuery(novel.id);
  const runner = usePublishNovelRun(novel.id);
  const pricing = useCloverPricingQuery().data;
  const lastChoiceRef = useRef<{ choice: PublishChoice; isPolicyV2Enabled: boolean } | undefined>(undefined);

  async function openPublish(status: NovelPublicationStatus): Promise<PublishRunResult> {
    const range = toPublishRange(status);
    // 거둔 공개를 고친 것 없이 다시 여는 것처럼 고를 범위가 없어도 보낼 것은 있다 — 그때는 지금 공개 범위다.
    // 모달을 연 때의 스위치 값을 모달과 요청이 함께 쓴다 — 가격 응답이 그사이 도착해도 모달이 받지 않은 칸을 보내지 않게.
    const isPolicyV2Enabled = pricing?.novelPublicPolicyV2Enabled === true;
    const choice = await PublishNovelModal.call({
      mode: status.published ? "republish" : "publish",
      range: range ?? { min: status.publishedChapterCount, max: status.publishedChapterCount },
      status,
      policyV2: isPolicyV2Enabled && pricing !== undefined ? { freeChapterCount: pricing.novelFreeChapterCount } : undefined,
    });
    if (choice === undefined) return false;
    lastChoiceRef.current = { choice, isPolicyV2Enabled };
    return runner.run(toPublishRequests({ status, chapters: novel.chapters, choice, isPolicyV2Enabled }));
  }

  async function retry(): Promise<PublishRunResult> {
    const status = publication.data;
    if (status === undefined) return false;
    const last = lastChoiceRef.current ?? {
      choice: { targetOrdinal: status.publishedChapterCount, freeByOrdinal: {}, changeSummaries: {} },
      isPolicyV2Enabled: false,
    };
    return runner.run(toPublishRequests({ status, chapters: novel.chapters, ...last }));
  }

  /** 신청 취소면 끝난 뒤 공개 상태를 다시 받아 결과를 돌려준다(`toCancelReviewOutcome`). 거두기는 결과를 말하지 않는다. */
  async function openWithdraw(mode: "withdraw" | "cancelReview") {
    const isDone = await WithdrawNovelPublicationModal.call({ novelId: novel.id, mode });
    if (!isDone || mode === "withdraw") return undefined;
    const refreshed = await publication.refetch();
    return toCancelReviewOutcome(refreshed.isSuccess ? refreshed.data : undefined);
  }

  return {
    publication,
    runState: runner.state,
    clearFailure: runner.clearFailure,
    openPublish,
    retry,
    openWithdraw,
  };
}
