import type { ViewerIllustration } from "./readerBlocks";

/** 내 소설 화 응답의 삽화 한 장. 자리를 문단 번호가 아니라 그 개정의 블록 id 로 가리키고, 비어 있으면 위치 확인
 * 필요(앵커 문단이 사라진 그림)다. */
export type OwnerIllustration = Omit<ViewerIllustration, "paragraphIndex" | "placement"> & {
  anchorBlockId: string | null;
  placement: ViewerIllustration["placement"] | null;
};

/**
 * 내 소설 화 응답의 삽화를 읽기 화면의 모양으로 — 앵커 블록 id 를 같은 개정의 블록 순번(= 문단 번호)으로 바꾼다.
 * 위치 확인이 필요한 그림과 블록을 못 찾는 그림은 읽기 화면에 서지 않는다(편집 보드가 따로 보인다).
 *
 * 응답에 삽화 칸이 없으면 빈 목록으로 읽는다. 타입상 늘 오는 칸이지만, API 만 삽화 칸을 더하기 전으로 되돌린 동안에는
 * 칸이 없고, 그때 읽기 화면이 깨지지 않고 글만 보여야 한다.
 */
export function toOwnerViewerIllustrations(revision: {
  blocks: readonly { id: string }[];
  illustrations?: readonly OwnerIllustration[];
}): ViewerIllustration[] {
  const indexById = new Map(revision.blocks.map((block, index) => [block.id, index]));
  return (revision.illustrations ?? []).flatMap((illustration) => {
    const { anchorBlockId, placement } = illustration;
    const paragraphIndex = anchorBlockId === null ? undefined : indexById.get(anchorBlockId);
    if (paragraphIndex === undefined || placement === null) return [];
    return [
      {
        paragraphIndex,
        placement,
        order: illustration.order,
        source: illustration.source,
        url: illustration.url,
        width: illustration.width,
        height: illustration.height,
        withheld: illustration.withheld,
        withheldReason: illustration.withheldReason,
      },
    ];
  });
}

/** 노벨 화 응답의 삽화. 응답이 이미 읽기 화면의 모양이다. 칸이 없으면 빈 목록으로 읽는다(이유는 소유자 쪽과 같다). */
export function toPublicViewerIllustrations(chapter: {
  illustrations?: readonly ViewerIllustration[];
}): readonly ViewerIllustration[] {
  return chapter.illustrations ?? [];
}
