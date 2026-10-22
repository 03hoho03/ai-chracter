import type { ViewerIllustration } from "../model/viewerSource";

/** 화 본문을 이루는 블록 — 문단 하나 또는 삽화 하나. 두 넘김 방식이 같은 목록을 그린다. */
export type ReaderBlock =
  | { kind: "paragraph"; index: number }
  | {
      kind: "illustration";
      /** 화 안에서 그림 자리를 가리키는 키(`문단-앞뒤-그 자리 안 순번`). 렌더 키이자 쪽 나누기가 그림을 찾는 표식이다. */
      key: string;
      illustration: ViewerIllustration;
    };

/**
 * 문단과 삽화를 읽는 순서대로 편다 — 문단 i 앞 그림들(순서대로) → 문단 i → 문단 i 뒤 그림들(순서대로). 그림이 없으면
 * 문단만이다. 문단을 차례로 돌며 그 자리의 그림을 꺼내므로 본문 범위 밖 문단을 가리키는 그림은 저절로 빠진다 — 같은
 * 개정의 응답이라 생기지 않지만, 생기면 화 전체를 깨는 대신 그 그림만 빠진다.
 */
export function toReaderBlocks(paragraphCount: number, illustrations: readonly ViewerIllustration[]): ReaderBlock[] {
  const spots = new Map<string, ViewerIllustration[]>();
  for (const illustration of illustrations) {
    const spot = `${illustration.paragraphIndex}-${illustration.placement}`;
    spots.set(spot, [...(spots.get(spot) ?? []), illustration]);
  }

  const blocks: ReaderBlock[] = [];
  const pushSpot = (spot: string) => {
    const sorted = [...(spots.get(spot) ?? [])].sort((a, b) => a.order - b.order);
    for (const [rank, illustration] of sorted.entries()) {
      blocks.push({ kind: "illustration", key: `${spot}-${rank}`, illustration });
    }
  };
  for (let index = 0; index < paragraphCount; index += 1) {
    pushSpot(`${index}-before`);
    blocks.push({ kind: "paragraph", index });
    pushSpot(`${index}-after`);
  }
  return blocks;
}

/**
 * 페이지 모드 쪽 나누기가 다시 재야 하는지 가르는 키 — 그림 블록의 높이를 정하는 것(자리·크기·원작 캡션·사유 안내와
 * 그 글)만 담는다. 같은 판을 보는 동안 응답을 다시 받아 그림이 내려지거나 원작 제한이 걸리고 풀리면 블록 높이가 바뀌는데,
 * 판이 같아 읽기 화면은 다시 마운트되지 않는다 — 이 키가 바뀌면 쪽을 다시 잰다. 서명 주소만 바뀌면 상자 크기가 같아
 * 키도 같다. 그림이 없으면 빈 글자다.
 */
export function toIllustrationLayoutKey(blocks: readonly ReaderBlock[]): string {
  return blocks
    .flatMap((block) => {
      if (block.kind !== "illustration") return [];
      const { width, height, source, withheld, withheldReason } = block.illustration;
      return [JSON.stringify([block.key, width, height, source === "original", withheld, withheldReason])];
    })
    .join("|");
}
