import { useRef } from "react";

import { useNovelPublicationQuery, type NovelPublicationStatus } from "@/entities/novel";

import { usePublishNovelRun } from "../api/usePublishNovelRun";
import { PublishNovelModal } from "../ui/PublishNovelModal";
import { WithdrawNovelPublicationModal } from "../ui/WithdrawNovelPublicationModal";
import { toPublishRange, toPublishRequests } from "./publicationView";

type PublishableNovel = { id: string; chapters: readonly { id: string; ordinal: number }[] };

/** 작품 정보의 공개 절과 편집 보드의 공개 버튼이 함께 쓰는 공개 동작 — 공개 상태 조회, 공개 모달을 열어 고른 범위를
 * 화 하나씩 보내기, 실패 뒤 같은 범위로 다시 시도, 거두기 모달. 공개가 끝나면(전부 성공) `true` 를 돌려준다. */
export function useNovelPublishActions(novel: PublishableNovel) {
  const publication = useNovelPublicationQuery(novel.id);
  const runner = usePublishNovelRun(novel.id);
  const lastTargetRef = useRef<number | undefined>(undefined);

  async function openPublish(status: NovelPublicationStatus): Promise<boolean> {
    const range = toPublishRange(status);
    // 거둔 공개를 고친 것 없이 다시 여는 것처럼 고를 범위가 없어도 보낼 것은 있다 — 그때는 지금 공개 범위다.
    const target = await PublishNovelModal.call({
      mode: status.published ? "republish" : "publish",
      range: range ?? { min: status.publishedChapterCount, max: status.publishedChapterCount },
      chapterCount: status.chapterCount,
    });
    if (target === undefined) return false;
    lastTargetRef.current = target;
    return runner.run(toPublishRequests({ status, chapters: novel.chapters, targetOrdinal: target }));
  }

  async function retry(): Promise<boolean> {
    const status = publication.data;
    if (status === undefined) return false;
    const target = lastTargetRef.current ?? status.publishedChapterCount;
    return runner.run(toPublishRequests({ status, chapters: novel.chapters, targetOrdinal: target }));
  }

  return {
    publication,
    runState: runner.state,
    clearFailure: runner.clearFailure,
    openPublish,
    retry,
    openWithdraw: () => WithdrawNovelPublicationModal.call({ novelId: novel.id }),
  };
}
