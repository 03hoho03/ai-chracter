import {
  isOutlineFlowChapter,
  toBatchRangeLabel,
  toRefundSentence,
  type NovelChapterSummary,
  type NovelJobResponse,
} from "@/entities/novel";
import { assertNever } from "@/shared/lib/assertNever";

/** 실패한 작업을 다시 시도할 때 다시 여는 흐름. 화 만들기는 경계 고르기를, 다시 만들기는 그 묶음의 확인을, 구성안으로 쓴 화의 다시
 * 만들기는 그 화의 확인을, 전체 구성안·장면 구성안·원고는 그 금액 확인을 다시 연다 — 같은 요청을 그대로 다시 보내지 않고 이용자가 금액을
 * 다시 본다. */
export type RetryTarget =
  | { kind: "generate" }
  | { kind: "regenerate"; batchId: string }
  | { kind: "outlineRegenerate"; chapterId: string }
  | { kind: "outline" }
  | { kind: "episodeOutline"; episodeKey: string }
  | { kind: "outlineChapter"; episodeKey: string };

/** 구성안을 만들 때 금액 줄 아래에 붙이는 환불 안내. 쓸 수 있는 구성안을 승인하지 않는 것은 이용자의 선택이라 돌려주지 않고,
 * 만들지 못한 실패는 서버가 전액 돌려준다. */
export const OUTLINE_SPEND_FOOTNOTE = "승인하지 않아도 쓴 클로버는 돌아오지 않아요. 만들지 못하면 모두 돌려드려요.";

/** 다시 시도를 가를 때 작업 응답 밖에서 가져오는 것. `chapters` 는 상세의 목차(다시 만든 화가 구성안으로 쓴 화인지 본다), `episodeKey` 는
 * 이 화면이 시작한 장면 구성안·원고 작업의 화 키다 — 작업 응답에는 화 키가 없어, 새로고침·다른 탭에서 온 작업은 모른다. */
type RetryContext = {
  chapters?: readonly Pick<NovelChapterSummary, "id" | "batchId" | "episodeOutlineId">[];
  episodeKey?: string | null;
};

export function toRetryTarget(job: NovelJobResponse, context: RetryContext = {}): RetryTarget | undefined {
  // 원래 대화가 바뀌어 실패한 작업은 다시 해도 같은 결과라 다시 시도를 내밀지 않는다(구성안은 담을 대화를 다시 승인해야 한다).
  if (job.failureReason === "source_changed") return undefined;
  const episodeKey = context.episodeKey ?? undefined;
  switch (job.kind) {
    // 남은 대화 한 번에도 다시 시도는 경계 고르기를 다시 여는 것이다 — 그사이 만든 묶음이 있으면 남은 대화가 줄어 견적이 바뀌므로 같은
    // 요청을 그대로 다시 보내지 않는다.
    case "chapter_generate":
    case "chain_generate":
      return { kind: "generate" };
    case "chapter_regenerate": {
      // 구성안으로 쓴 화는 옛 묶음 라우트가 409 로 거절한다 — 새 라우트의 확인을 다시 연다.
      const chapter = toRegeneratedChapter(job, context.chapters ?? []);
      if (chapter !== undefined && isOutlineFlowChapter(chapter)) return { kind: "outlineRegenerate", chapterId: chapter.id };
      return job.batchId === null ? undefined : { kind: "regenerate", batchId: job.batchId };
    }
    case "outline_generate":
      return { kind: "outline" };
    case "episode_outline_generate":
      return episodeKey === undefined ? undefined : { kind: "episodeOutline", episodeKey };
    case "outline_chapter_generate":
      return episodeKey === undefined ? undefined : { kind: "outlineChapter", episodeKey };
    case "ai_edit":
      return undefined;
    default:
      return assertNever(job.kind);
  }
}

/** 다시 만들기 작업이 가리키는 화 — 작업의 화, 없으면 작업 묶음의 첫 화. */
function toRegeneratedChapter(
  job: NovelJobResponse,
  chapters: readonly Pick<NovelChapterSummary, "id" | "batchId" | "episodeOutlineId">[],
) {
  return (
    chapters.find((chapter) => chapter.id === job.chapterId) ??
    (job.batchId === null ? undefined : chapters.find((chapter) => chapter.batchId === job.batchId))
  );
}

/** 성공한 작업의 결과 문장. 만든 화들을 범위로 말하고, 덜 나온 화의 몫을 서버가 돌려줬으면 그 금액을 덧붙인다(성공도
 * 일부 환불일 수 있다). 전체 구성안·장면 구성안은 화를 만들지 않는다 — 초안이 왔으니 확인하고 승인하라고 말한다. 원고는 구성안의 한 화를
 * 쓴 것이라 그 화 번호를 말한다. */
export function toDoneMessage(job: NovelJobResponse, chapters: readonly NovelChapterSummary[]): string {
  const refund = toRefundSentence(job.refundedAmount);
  if (job.kind === "outline_generate") return `전체 구성안을 만들었어요. 화마다 확인한 뒤 승인해주세요.${refund}`;
  if (job.kind === "episode_outline_generate") return `장면 구성안을 만들었어요. 장면을 확인한 뒤 승인해주세요.${refund}`;
  if (job.kind === "outline_chapter_generate") {
    const chapter = chapters.find((item) => item.id === job.chapterId);
    return `${chapter === undefined ? "구성안으로 새 화를" : `${chapter.ordinal}화를`} 썼어요.${refund}`;
  }
  if (job.kind === "chain_generate") return `남은 대화를 소설로 만들었어요.${refund}`;
  const rangeLabel = job.batchId === null ? undefined : toBatchRangeLabel(chapters, job.batchId);
  const verb = job.kind === "chapter_regenerate" ? "다시 만들었어요" : "만들었어요";
  return `${rangeLabel === undefined ? "화를" : `${rangeLabel}를`} ${verb}.${refund}`;
}
