import type { NovelPublicationScreening, NovelPublicationStatus } from "@/entities/novel";
import { koreanParticle } from "@/shared/lib/text/koreanParticle";

/** 원작 때문에 새로 공개할 수 없는 이유 — 원작자가 공개를 허락하지 않았거나(`permission`), 원작이 지금 공개돼 있지
 * 않다(`source` — 비공개·이용제한·삭제, 공개 목록에서 빠짐). */
export type PublishSourceBlock = "permission" | "source";

/** 작품 정보의 "노벨 공개" 절이 그릴 상태. 요청 중("확인 중")과 요청 실패는 화면이 따로 안다 — 서버가 주는 상태만으로
 * 가른다.
 *
 * - `noChapters`: 화가 없어 공개할 것이 없다.
 * - `unpublished`: 공개한 적이 없고 공개할 수 있다.
 * - `blocked`: 공개한 적이 없고 원작 때문에 공개할 수 없다.
 * - `restricted`: 운영자가 노벨에서 내렸다(거둠·공개 중 무관하게 이것이 앞선다).
 * - `withdrawn`: 게시자가 공개를 거뒀다. 원작이 공개돼 있지 않으면 다시 열 수 없다.
 * - `public`: 공개 중. 아직 공개하지 않은 화 수, 원작 때문에 더 공개할 수 없는가, 공개한 뒤 고친 화·제목·소개,
 *   그리고 다시 공개할 것이 있는가. */
export type PublicationView =
  | { kind: "noChapters" }
  | { kind: "unpublished" }
  | { kind: "blocked"; block: PublishSourceBlock }
  | { kind: "restricted" }
  | { kind: "withdrawn"; canReopen: boolean }
  | {
      kind: "public";
      publishedCount: number;
      unpublishedCount: number;
      newBlock: PublishSourceBlock | undefined;
      changedOrdinals: number[];
      metadataChanged: boolean;
      canRepublish: boolean;
    };

function toSourceBlock(block: NovelPublicationStatus["newPublishBlock"]): PublishSourceBlock | undefined {
  if (block === null) return undefined;
  return block === "source_permission" ? "permission" : "source";
}

export function toPublicationView(status: NovelPublicationStatus): PublicationView {
  if (status.moderationStatus === "restricted") return { kind: "restricted" };
  const newBlock = toSourceBlock(status.newPublishBlock);
  if (!status.published) {
    if (status.chapterCount === 0) return { kind: "noChapters" };
    return newBlock === undefined ? { kind: "unpublished" } : { kind: "blocked", block: newBlock };
  }
  if (status.visibility === "withdrawn") return { kind: "withdrawn", canReopen: status.republishBlock === null };
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
    canRepublish: (unpublishedCount > 0 && newBlock === undefined) || (hasChanges && status.republishBlock === null),
  };
}

/** 공개 모달에서 고를 수 있는 "N화까지"의 범위. 1화부터 이어진 화만 공개하므로 고르는 것은 끝 화 하나다 — 아래 끝은
 * 지금 공개한 범위(줄일 수 없다 — 줄이는 길은 마지막 묶음 삭제나 거두기다), 위 끝은 새로 공개할 수 있으면 마지막 화,
 * 없으면 지금 공개한 범위다. 고를 것이 없으면(화가 없거나 공개한 적 없이 막힘) `undefined`. */
export function toPublishRange(status: NovelPublicationStatus): { min: number; max: number } | undefined {
  const min = Math.max(status.publishedChapterCount, 1);
  const max = status.newPublishBlock === null ? status.chapterCount : status.publishedChapterCount;
  return max < min ? undefined : { min, max };
}

/** 공개할 때 보낼 요청들(요청 하나 = 화 하나, 차례대로). 먼저 이미 공개한 화 중 고친 것을 다시 내고, 그다음 공개한
 * 범위 다음 화부터 `targetOrdinal` 화까지 새로 공개한다 — 앞 화가 걸려 멈추면 그 앞까지는 공개된 채 남고 1화부터의
 * 이어짐이 깨지지 않는다. 화를 다시 내지 않아도 제목·소개가 바뀌었거나 거둔 공개를 다시 여는 것이면 화 없이 한 번
 * 보낸다(`null`). 서버는 어느 요청에서든 바뀐 제목·소개를 함께 심사해 내고 거둔 공개를 다시 연다. */
export function toPublishRequests({
  status,
  chapters,
  targetOrdinal,
}: {
  status: NovelPublicationStatus;
  chapters: readonly { id: string; ordinal: number }[];
  targetOrdinal: number;
}): (string | null)[] {
  const idByOrdinal = new Map(chapters.map((chapter) => [chapter.ordinal, chapter.id]));
  const published = status.publishedChapterCount;
  const changed = [...status.changedChapterOrdinals].filter((ordinal) => ordinal <= published).sort((a, b) => a - b);
  const fresh: number[] = [];
  for (let ordinal = published + 1; ordinal <= targetOrdinal; ordinal += 1) fresh.push(ordinal);
  const ids = [...changed, ...fresh].flatMap((ordinal) => {
    const id = idByOrdinal.get(ordinal);
    return id === undefined ? [] : [id];
  });
  if (ids.length === 0 && (status.metadataChanged || status.visibility === "withdrawn")) return [null];
  return ids;
}

const CHAPTER_PART_LABELS = {
  chapter_title: "화 제목",
  author_note: "작가의 말",
  chapter_body: "본문",
} as const;

const NOVEL_PART_LABELS = {
  novel_title: "소설 제목",
  synopsis: "소개",
} as const;

type FlaggedPart = NovelPublicationScreening["flaggedParts"][number];

function isChapterPart(part: FlaggedPart): part is keyof typeof CHAPTER_PART_LABELS {
  return part in CHAPTER_PART_LABELS;
}

function isNovelPart(part: FlaggedPart): part is keyof typeof NOVEL_PART_LABELS {
  return part in NOVEL_PART_LABELS;
}

/** 심사에 걸린 공개의 안내 — 어느 화의 어느 글이 걸렸는지와, 무엇을 고친 뒤 다시 공개하면 되는지. 심사 모델이 쓴
 * 사유는 게시자에게 보이지 않는다(서버가 싣지 않는다). `fixOrdinal` 은 고치러 갈 화(화의 글이 걸렸을 때만). */
export function toRejectionNotice(screening: Pick<NovelPublicationScreening, "chapterOrdinal" | "flaggedParts">): {
  message: string;
  fixOrdinal: number | undefined;
} {
  const ordinal = screening.chapterOrdinal;
  const novelParts = screening.flaggedParts.filter(isNovelPart).map((part) => NOVEL_PART_LABELS[part]);
  const chapterParts = screening.flaggedParts.filter(isChapterPart).map((part) => CHAPTER_PART_LABELS[part]);
  const groups: string[] = [];
  if (novelParts.length > 0) groups.push(novelParts.join("·"));
  if (chapterParts.length > 0) groups.push(ordinal === null ? chapterParts.join("·") : `${ordinal}화의 ${chapterParts.join("·")}`);
  if (groups.length === 0) groups.push(ordinal === null ? "글" : `${ordinal}화`);
  const subject = groups.join(", ");
  const fixOrdinal = ordinal !== null && (chapterParts.length > 0 || novelParts.length === 0) ? ordinal : undefined;
  const fixNoun = fixOrdinal !== undefined ? `${fixOrdinal}화` : novelParts.join("·") || "글";
  return {
    message: `${subject}${koreanParticle(subject, "이/가")} 운영 정책에 맞지 않는 내용으로 확인돼 공개하지 못했어요. ${fixNoun}${koreanParticle(fixNoun, "을/를")} 고친 뒤 다시 공개해 주세요.`,
    fixOrdinal,
  };
}

/** "1~5화는 무료, 그 뒤 화는 화마다 클로버 30개예요." 값을 아직 모르면 숫자 없이 말한다. */
export function toPublishPriceSentence(pricing: { freeChapterCount: number; chapterPrice: number } | undefined): string {
  if (pricing === undefined) return "앞 몇 화는 무료이고, 그 뒤 화는 화마다 클로버로 소장해 읽어요.";
  const free = pricing.freeChapterCount > 0 ? `1~${pricing.freeChapterCount}화는 무료, 그 뒤 화는` : "모든 화를";
  return `${free} 화마다 클로버 ${pricing.chapterPrice.toLocaleString()}개예요.`;
}

/** 공개 중인 소설에서 아직 노벨에 반영되지 않은 것들 — 공개하지 않은 화, 원작 때문에 더 공개할 수 없는 사정, 공개한
 * 뒤 고친 화·제목·소개. `republishBlocked` 는 원작이 지금 공개돼 있지 않아 고친 것도 다시 낼 수 없는가다. */
export function toPublicPendingLines(
  view: Extract<PublicationView, { kind: "public" }>,
  { republishBlocked }: { republishBlocked: boolean },
): string[] {
  const lines: string[] = [];
  const first = view.publishedCount + 1;
  const last = view.publishedCount + view.unpublishedCount;
  if (view.unpublishedCount > 0) {
    if (view.newBlock === undefined) {
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
    if (republishBlocked) lines.push("원작이 지금 공개돼 있지 않아 고친 내용을 다시 공개할 수 없어요.");
  }
  return lines;
}
