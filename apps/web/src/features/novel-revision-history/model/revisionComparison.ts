import type { NovelRevisionResponse } from "@/entities/novel";

type ComparableIllustration = Pick<
  NovelRevisionResponse["illustrations"][number],
  "anchorBlockId" | "placement" | "order" | "assetId" | "source"
>;

/** 두 판을 견주는 데 쓰는 칸만 — 판 응답(`NovelRevisionResponse`)이 그대로 들어간다. */
export type ComparableRevision = {
  paragraphs: readonly string[];
  blocks: readonly { id: string }[];
  illustrations: readonly ComparableIllustration[];
  unplacedIllustrations: readonly ComparableIllustration[];
};

function isSameText(a: Pick<ComparableRevision, "paragraphs">, b: Pick<ComparableRevision, "paragraphs">): boolean {
  return a.paragraphs.length === b.paragraphs.length && a.paragraphs.every((text, index) => text === b.paragraphs[index]);
}

/** 독자가 보는 그림 배치의 지문 — 자리마다(문단 번호·앞뒤) 그 자리 안 순서대로 그림(자산·출처), 그리고 자리를 잃은 그림.
 * 블록 id·순서 값 자체는 판마다 달라도 화면이 같으면 지문이 같다(되돌린 판은 블록 id 가 다르다). */
function toIllustrationFingerprint(revision: ComparableRevision): string {
  const indexById = new Map(revision.blocks.map((block, index) => [block.id, index]));
  const placed = revision.illustrations
    .map((illustration) => {
      const index = illustration.anchorBlockId === null ? undefined : indexById.get(illustration.anchorBlockId);
      return { spot: `${index ?? "?"}-${illustration.placement ?? "?"}`, illustration };
    })
    .sort((a, b) => {
      if (a.spot !== b.spot) return a.spot < b.spot ? -1 : 1;
      return a.illustration.order - b.illustration.order;
    })
    .map(({ spot, illustration }) => `${spot}:${illustration.assetId}:${illustration.source}`);
  const unplaced = revision.unplacedIllustrations
    .map((illustration) => `${illustration.assetId}:${illustration.source}`)
    .sort();
  return JSON.stringify([placed, unplaced]);
}

/** 두 판이 글은 같고 삽화만 다른가. 그러면 글 비교는 "바뀐 곳이 없어요"를 말하므로, 화면은 삽화만 바뀌었다고 말한다. 글이
 * 다르면 글 비교가 맡고, 둘 다 같으면(같은 글 판으로 되돌린 판) 지금 문장 그대로다. 삽화 스위치가 꺼진 응답은 그림이 빈
 * 목록이라 늘 거짓이다. */
export function isIllustrationOnlyChange(before: ComparableRevision, after: ComparableRevision): boolean {
  return isSameText(before, after) && toIllustrationFingerprint(before) !== toIllustrationFingerprint(after);
}

/** 되돌리기 버튼 위에 "적용하지 않은 AI 수정안은 사라진다"를 말할지. 서버는 글이 바뀌는 판에서만 수정안을 버리므로, 되돌릴
 * 판 글이 지금 글과 같으면 말하지 않는다. 두 판 글을 아직 받지 못했으면 말한다 — 모른 채 되돌려 돈 낸 수정안을 잃는 쪽이 더
 * 나쁘다. */
export function shouldWarnPendingAiEditsLost({
  hasPendingAiEdits,
  target,
  current,
}: {
  hasPendingAiEdits: boolean;
  target: Pick<ComparableRevision, "paragraphs"> | undefined;
  current: Pick<ComparableRevision, "paragraphs"> | undefined;
}): boolean {
  if (!hasPendingAiEdits) return false;
  if (target === undefined || current === undefined) return true;
  return !isSameText(target, current);
}
