import type { NovelPublicationScreening, NovelPublicationStatus } from "@/entities/novel";
import { koreanParticle } from "@/shared/lib/text/koreanParticle";

import { toRepublishOrdinals } from "./publishPricing";

/** 원작 때문에 새로 공개할 수 없는 이유 — 원작자가 공개를 허락하지 않았거나(`permission`), 원작이 지금 공개돼 있지
 * 않다(`source` — 비공개·이용제한·삭제, 공개 목록에서 빠짐). */
export type PublishSourceBlock = "permission" | "source";

/** 작품 정보의 "노벨 공개" 절이 그릴 상태. 요청 중("확인 중")과 요청 실패는 화면이 따로 안다 — 서버가 주는 상태만으로
 * 가른다.
 *
 * - `noChapters`: 화가 없어 공개할 것이 없다.
 * - `unpublished`: 공개한 적이 없고 공개할 수 있다.
 * - `blocked`: 공개한 적이 없고 원작 때문에 공개할 수 없다.
 * - `restricted`: 운영자가 노벨에서 내렸다(거둠·공개 중·승인 대기 무관하게 이것이 앞선다).
 * - `inReview`: 첫 공개를 신청했고 운영자가 1화를 확인하고 있다. 공개 범위는 `withdrawn` 이지만 게시자가 거둔 것이 아니다.
 * - `reviewRejected`: 운영자가 첫 공개를 반려했다. `reason` 은 운영자가 쓴 글 그대로다. 반려된 공개는 독자에게 보인 적이
 *   없어 새로 공개하는 것과 같은 원작 판정을 받는다 — 그 판정이 막지 않고 화가 있어야 다시 신청할 수 있다(`canReapply`),
 *   막혔으면 `block` 이 그 까닭이다.
 * - `withdrawn`: 게시자가 공개를 거뒀다. 원작이 공개돼 있지 않거나 운영자가 판매를 멈췄으면 다시 열 수 없다. 승인
 *   없이 열 수 있게 된 대기·반려 행(정책 스위치를 끈 뒤 남은 것)도 여기로 온다.
 * - `public`: 공개 중. 아직 공개하지 않은 화 수, 원작 때문에 더 공개할 수 없는가, 공개한 뒤 고친 화·제목·소개,
 *   그리고 다시 공개할 것이 있는가.
 *
 * `salesStopped` 는 운영자가 판매를 멈췄는가다. 멈춘 동안은 새 화·다시 공개·다시 열기를 서버가 모두 막으므로 공개할
 * 것이 있어도 공개 버튼을 내지 않는다(거두기는 된다). 운영 이용제한이 걸려 있으면 그것이 앞선다. */
export type PublicationView =
  | { kind: "noChapters" }
  | { kind: "unpublished" }
  | { kind: "blocked"; block: PublishSourceBlock }
  | { kind: "restricted" }
  | { kind: "inReview" }
  | { kind: "reviewRejected"; reason: string; canReapply: boolean; block: PublishSourceBlock | undefined }
  | { kind: "withdrawn"; canReopen: boolean; salesStopped: boolean }
  | {
      kind: "public";
      publishedCount: number;
      unpublishedCount: number;
      newBlock: PublishSourceBlock | undefined;
      changedOrdinals: number[];
      metadataChanged: boolean;
      canRepublish: boolean;
      salesStopped: boolean;
    };

function toSourceBlock(block: NovelPublicationStatus["newPublishBlock"]): PublishSourceBlock | undefined {
  if (block === null) return undefined;
  return block === "source_permission" ? "permission" : "source";
}

export function toPublicationView(status: NovelPublicationStatus): PublicationView {
  if (status.moderationStatus === "restricted") return { kind: "restricted" };
  // 판매 중단 칸이 없는 옛 응답(`undefined`)은 멈추지 않은 것으로 읽는다.
  const salesStopped = status.salesStopped === true;
  const newBlock = toSourceBlock(status.newPublishBlock);
  // 심사 칸이 없는 옛 응답(`undefined`)은 엄격 비교에 걸리지 않아 아래의 지금 판정으로 떨어진다.
  const inReviewRow = status.reviewStatus === "pending" || status.reviewStatus === "rejected";
  // 정책 스위치를 켰다가 끄면 대기·반려 행이 남는데, 서버는 그 행을 승인 없이 다시 연다(`reviewRequired` 거짓). 그래서
  // 심사 상태가 아니라 거둔 공개로 그린다. 독자에게 보인 적 없는 행을 여는 것이라 새로 공개하는 것과 같은 원작 판정을 받는다.
  if (inReviewRow && status.reviewRequired === false) {
    return { kind: "withdrawn", canReopen: newBlock === undefined && !salesStopped, salesStopped };
  }
  if (status.reviewStatus === "pending") return { kind: "inReview" };
  if (status.reviewStatus === "rejected") {
    return {
      kind: "reviewRejected",
      reason: status.reviewReason ?? "",
      canReapply: newBlock === undefined && status.chapterCount > 0,
      block: newBlock,
    };
  }
  if (!status.published) {
    if (status.chapterCount === 0) return { kind: "noChapters" };
    return newBlock === undefined ? { kind: "unpublished" } : { kind: "blocked", block: newBlock };
  }
  if (status.visibility === "withdrawn") {
    return { kind: "withdrawn", canReopen: status.republishBlock === null && !salesStopped, salesStopped };
  }
  const unpublishedCount = Math.max(status.chapterCount - status.publishedChapterCount, 0);
  const changedOrdinals = [...status.changedChapterOrdinals].sort((a, b) => a - b);
  const hasChanges = changedOrdinals.length > 0 || status.metadataChanged;
  return {
    kind: "public",
    publishedCount: status.publishedChapterCount,
    unpublishedCount,
    newBlock,
    changedOrdinals,
    metadataChanged: status.metadataChanged,
    canRepublish:
      !salesStopped &&
      ((unpublishedCount > 0 && newBlock === undefined) || (hasChanges && status.republishBlock === null)),
    salesStopped,
  };
}

/** 공개 모달에서 고를 수 있는 "N화까지"의 범위. 1화부터 이어진 화만 공개하므로 고르는 것은 끝 화 하나다 — 아래 끝은
 * 지금 공개한 범위(줄일 수 없다 — 줄이는 길은 마지막 묶음 삭제나 거두기다), 위 끝은 새로 공개할 수 있으면 마지막 화,
 * 없으면(원작 때문에, 또는 운영자가 판매를 멈춰서) 지금 공개한 범위다. 고를 것이 없으면(화가 없거나 공개한 적 없이 막힘) `undefined`.
 *
 * 첫 공개에 운영자 승인이 필요하면(`reviewRequired`) 1화만 고를 수 있다 — 승인을 기다리는 동안 다음 화 요청은 서버가
 * 막으므로, 신청하는 것은 1화 하나다. */
export function toPublishRange(status: NovelPublicationStatus): { min: number; max: number } | undefined {
  if (status.reviewRequired) {
    return status.chapterCount > 0 && status.newPublishBlock === null ? { min: 1, max: 1 } : undefined;
  }
  const min = Math.max(status.publishedChapterCount, 1);
  const canPublishNew = status.newPublishBlock === null && status.salesStopped !== true;
  const max = canPublishNew ? status.chapterCount : status.publishedChapterCount;
  return max < min ? undefined : { min, max };
}

/** 공개 모달에서 고른 것. `freeByOrdinal` 은 새로 공개하는 화 중 가격을 고른 화(번호 → 무료인가) — 앞 화와 무료 고정
 * 번호는 고를 것이 없어 들어 있지 않다. `changeSummaries` 는 다시 내는 고친 화의 변경 요약(번호 → 글)이다. 둘 다 노벨
 * 정책 스위치가 켜졌을 때만 채운다. */
export type PublishChoice = {
  targetOrdinal: number;
  freeByOrdinal: Readonly<Record<number, boolean>>;
  changeSummaries: Readonly<Record<number, string>>;
};

/** 공개 요청 하나의 본문. `chapterId` 가 `null` 이면 화 없이 제목·소개만 내거나 거둔 공개를 다시 연다. */
export type PublishRequestBody = { chapterId: string | null; free?: boolean; changeSummary?: string };

/** 공개할 때 보낼 요청들(요청 하나 = 화 하나, 차례대로). 먼저 이미 공개한 화 중 고친 것을 다시 내고, 그다음 공개한
 * 범위 다음 화부터 고른 끝 화까지 새로 공개한다 — 앞 화가 걸려 멈추면 그 앞까지는 공개된 채 남고 1화부터의
 * 이어짐이 깨지지 않는다. 화를 다시 내지 않아도 제목·소개가 바뀌었거나 거둔 공개를 다시 여는 것이면 화 없이 한 번
 * 보낸다. 서버는 어느 요청에서든 바뀐 제목·소개를 함께 심사해 내고 거둔 공개를 다시 연다.
 *
 * 정책 스위치가 켜져 있으면 새 화에 고른 가격(`free`)을, 다시 내는 화에 변경 요약(`changeSummary`, 앞뒤 공백을 던 글)을
 * 싣는다. 가격을 고르지 않은 새 화(앞 화·무료 고정 번호)는 칸을 비워 서버가 무료로 두게 하고, 다시 내는 화는 가격을
 * 싣지 않는다 — 비우면 서버가 지금 가격을 그대로 둔다. 꺼져 있으면 두 칸 모두 싣지 않는다(서버가 보지 않는다).
 *
 * 첫 공개에 운영자 승인이 필요하면(`reviewRequired`) 첫 요청 하나만 보낸다 — 그 요청이 승인 대기를 만들고, 대기 중의
 * 다음 요청은 서버가 409 로 막는다. */
export function toPublishRequests({
  status,
  chapters,
  choice,
  isPolicyV2Enabled,
}: {
  status: NovelPublicationStatus;
  chapters: readonly { id: string; ordinal: number }[];
  choice: PublishChoice;
  isPolicyV2Enabled: boolean;
}): PublishRequestBody[] {
  const idByOrdinal = new Map(chapters.map((chapter) => [chapter.ordinal, chapter.id]));
  const published = status.publishedChapterCount;
  const changed = toRepublishOrdinals(status);
  const fresh: number[] = [];
  for (let ordinal = published + 1; ordinal <= choice.targetOrdinal; ordinal += 1) fresh.push(ordinal);
  const toBody = (ordinal: number, chapterId: string): PublishRequestBody => {
    if (!isPolicyV2Enabled) return { chapterId };
    if (ordinal <= published) {
      const summary = choice.changeSummaries[ordinal]?.trim() ?? "";
      return summary === "" ? { chapterId } : { chapterId, changeSummary: summary };
    }
    const free = choice.freeByOrdinal[ordinal];
    return free === undefined ? { chapterId } : { chapterId, free };
  };
  const bodies = [...changed, ...fresh].flatMap((ordinal) => {
    const id = idByOrdinal.get(ordinal);
    return id === undefined ? [] : [toBody(ordinal, id)];
  });
  const requests =
    bodies.length === 0 && (status.metadataChanged || status.visibility === "withdrawn") ? [{ chapterId: null }] : bodies;
  return status.reviewRequired ? requests.slice(0, 1) : requests;
}

/** 첫 공개를 신청한 뒤(승인 대기로 끝난 공개) 알리는 말. 작품 정보의 공개 절과 보드의 공개 버튼이 함께 쓴다. */
export const REVIEW_REQUESTED_MESSAGE = "공개를 신청했어요. 운영자가 확인하면 노벨에 열려요.";

/** 신청 취소를 보낸 뒤 다시 받은 공개 상태로 무엇이 일어났는지 가른다. 서버는 승인 대기면 신청을 지우고, 그사이 승인됐으면
 * 보통의 거두기를 한다 — 누른 버튼이 아니라 결과로 말해야 한다. 공개 상태 행이 없으면 취소됐고, 대기가 아니게 됐으면
 * 승인된 뒤 거둬졌다. 다시 받지 못했거나 아직 대기로 보이면 말할 것이 없다(`undefined`). */
export function toCancelReviewOutcome(
  status: Pick<NovelPublicationStatus, "published" | "reviewStatus"> | undefined,
): "cancelled" | "withdrawnAfterApproval" | undefined {
  if (status === undefined) return undefined;
  if (!status.published) return "cancelled";
  if (status.reviewStatus === "approved") return "withdrawnAfterApproval";
  return undefined;
}

const CHAPTER_PART_LABELS = {
  chapter_title: "화 제목",
  author_note: "작가의 말",
  chapter_body: "본문",
  illustration: "삽화",
} as const;

const NOVEL_PART_LABELS = {
  novel_title: "소설 제목",
  synopsis: "소개",
} as const;

/** 다시 낸 화의 변경 요약. 화의 글 라벨과 따로 둔다 — 고칠 자리가 편집 보드가 아니라 공개 모달이다. */
const CHANGE_SUMMARY_LABEL = "변경 요약";

type FlaggedPart = NovelPublicationScreening["flaggedParts"][number];

function isChapterPart(part: FlaggedPart): part is keyof typeof CHAPTER_PART_LABELS {
  return part in CHAPTER_PART_LABELS;
}

function isNovelPart(part: FlaggedPart): part is keyof typeof NOVEL_PART_LABELS {
  return part in NOVEL_PART_LABELS;
}

/** 심사에 걸린 공개의 안내 — 어느 화의 어느 글이 걸렸는지와, 무엇을 고친 뒤 다시 공개하면 되는지. 심사 모델이 쓴
 * 사유는 게시자에게 보이지 않는다(서버가 싣지 않는다). `fixOrdinal` 은 고치러 갈 화(화의 글이 걸렸을 때만).
 *
 * 변경 요약은 화에 딸린 글이지만 편집 보드가 아니라 공개 모달에서 쓴다 — 요약만 걸리면 고치러 갈 화가 없고, 다시
 * 공개하면서 요약을 고쳐 쓰라고 말한다. */
export function toRejectionNotice(screening: Pick<NovelPublicationScreening, "chapterOrdinal" | "flaggedParts">): {
  message: string;
  fixOrdinal: number | undefined;
} {
  const ordinal = screening.chapterOrdinal;
  const novelParts = screening.flaggedParts.filter(isNovelPart).map((part) => NOVEL_PART_LABELS[part]);
  const chapterParts = screening.flaggedParts.filter(isChapterPart).map((part) => CHAPTER_PART_LABELS[part]);
  const isSummaryFlagged = screening.flaggedParts.includes("change_summary");
  const chapterSubjects = isSummaryFlagged ? [...chapterParts, CHANGE_SUMMARY_LABEL] : chapterParts;
  const groups: string[] = [];
  if (novelParts.length > 0) groups.push(novelParts.join("·"));
  if (chapterSubjects.length > 0) {
    groups.push(ordinal === null ? chapterSubjects.join("·") : `${ordinal}화의 ${chapterSubjects.join("·")}`);
  }
  if (groups.length === 0) groups.push(ordinal === null ? "글" : `${ordinal}화`);
  const subject = groups.join(", ");
  const fixOrdinal =
    ordinal !== null && (chapterParts.length > 0 || (novelParts.length === 0 && !isSummaryFlagged)) ? ordinal : undefined;
  const fixTargets = [fixOrdinal !== undefined ? `${fixOrdinal}화` : novelParts.join("·")].filter((target) => target !== "");
  if (isSummaryFlagged) fixTargets.push(CHANGE_SUMMARY_LABEL);
  const [firstTarget = "글", secondTarget] = fixTargets;
  const fixNoun = secondTarget === undefined ? firstTarget : `${firstTarget}${koreanParticle(firstTarget, "과/와")} ${secondTarget}`;
  return {
    message: `${subject}${koreanParticle(subject, "이/가")} 운영 정책에 맞지 않는 내용으로 확인돼 공개하지 못했어요. ${fixNoun}${koreanParticle(fixNoun, "을/를")} 고친 뒤 다시 공개해 주세요.`,
    fixOrdinal,
  };
}

/** 공개 모달·공개 절의 가격 문장. 정책 스위치가 꺼져 있으면 "1~5화는 무료, 그 뒤 화는 화마다 클로버 30개예요.", 켜져
 * 있으면 그 뒤 화는 공개할 때 화마다 무료·유료를 고른다고 말한다. 값을 아직 모르면 숫자 없이 말한다. */
export function toPublishPriceSentence(
  pricing: { freeChapterCount: number; chapterPrice: number; isPolicyV2Enabled: boolean } | undefined,
): string {
  if (pricing === undefined) return "앞 몇 화는 무료이고, 그 뒤 화는 화마다 클로버로 소장해 읽어요.";
  const price = pricing.chapterPrice.toLocaleString();
  if (pricing.isPolicyV2Enabled) {
    const free = pricing.freeChapterCount > 0 ? `1~${pricing.freeChapterCount}화는 무료이고, 그 뒤 화는` : "모든 화는";
    return `${free} 공개할 때 화마다 무료나 유료(클로버 ${price}개)를 골라요.`;
  }
  const free = pricing.freeChapterCount > 0 ? `1~${pricing.freeChapterCount}화는 무료, 그 뒤 화는` : "모든 화를";
  return `${free} 화마다 클로버 ${price}개예요.`;
}

/** 공개 중인 소설에서 아직 노벨에 반영되지 않은 것들 — 공개하지 않은 화, 더 공개할 수 없는 사정(원작·판매 중단), 공개한
 * 뒤 고친 화·제목·소개. `republishBlock` 은 고친 것을 다시 낼 수 없는 이유다(상태 응답 그대로). */
export function toPublicPendingLines(
  view: Extract<PublicationView, { kind: "public" }>,
  { republishBlock }: { republishBlock: NovelPublicationStatus["republishBlock"] },
): string[] {
  const lines: string[] = [];
  const first = view.publishedCount + 1;
  const last = view.publishedCount + view.unpublishedCount;
  if (view.unpublishedCount > 0) {
    if (view.newBlock === undefined || view.salesStopped) {
      lines.push(`${first === last ? `${first}화는` : `${first}~${last}화는`} 아직 공개하지 않았어요.`);
    } else if (view.newBlock === "permission") {
      lines.push("원작자가 소설 허락을 바꿔 새 화는 더 공개할 수 없어요. 이미 공개한 화를 고친 내용은 다시 공개할 수 있어요.");
    } else {
      lines.push("원작이 지금 공개돼 있지 않아 새 화는 공개할 수 없어요.");
    }
  }
  const parts: string[] = [];
  if (view.changedOrdinals.length > 0) {
    parts.push(`화 ${view.changedOrdinals.length}개(${view.changedOrdinals.map((ordinal) => `${ordinal}화`).join("·")})`);
  }
  if (view.metadataChanged) parts.push("제목·소개");
  if (parts.length > 0) {
    lines.push(`공개한 뒤 고친 ${parts.join("와 ")}가 노벨에는 아직 옛 내용이에요.`);
    if (!view.salesStopped && republishBlock === "source_unavailable") {
      lines.push("원작이 지금 공개돼 있지 않아 고친 내용을 다시 공개할 수 없어요.");
    }
  }
  if (view.salesStopped && lines.length > 0) lines.push("판매가 멈춘 동안은 새 화와 고친 내용을 공개할 수 없어요.");
  return lines;
}
