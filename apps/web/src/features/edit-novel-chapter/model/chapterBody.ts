import type { ParagraphRange } from "./paragraphRange";

/** 문단 사이를 다시 이을 때 쓰는 구분. 서버도 저장할 때 문단을 빈 줄 하나로 다시 잇는다. */
const PARAGRAPH_SEPARATOR = "\n\n";

/** 빈 줄(공백만 있는 줄 포함)로 나눈 문단. 서버의 문단 나누기와 같은 규칙이다(앞뒤 공백을 걷고 빈 문단은 버리고,
 * 문단 안 줄바꿈 하나는 둔다).
 *
 * 화면은 지금 본문의 문단을 직접 나누지 않고 서버가 준 `paragraphs` 를 쓴다. 이 함수는 서버가 문단 배열을 주지
 * 않는 두 자리 — 이용자가 입력칸에 쓴 글, AI 수정안의 장 전체 본문 — 에만 쓴다. 수정안 본문은 서버가 이 규칙으로
 * 나눈 문단을 빈 줄 하나로 이어 저장한 것이라 같은 규칙으로 나누면 서버의 나누기와 어긋나지 않는다. */
export function splitChapterParagraphs(text: string): string[] {
  return text
    .split(/\n[ \t]*\n/)
    .map((paragraph) => paragraph.trim())
    .filter((paragraph) => paragraph.length > 0);
}

/** 직접 고친 글을 장 전체 본문으로 조립한다. 서버는 문단 범위를 모르고 장 전체 본문을 받으므로, 고른 범위를
 * 입력칸의 글로 바꾸고 범위 밖 문단은 그대로 붙인다. 입력칸을 비우면 고른 문단을 지운 것이 된다. */
export function assembleChapterBody(paragraphs: readonly string[], range: ParagraphRange, draft: string): string {
  return [
    ...paragraphs.slice(0, range.start),
    ...splitChapterParagraphs(draft),
    ...paragraphs.slice(range.end + 1),
  ].join(PARAGRAPH_SEPARATOR);
}

/** 고른 범위를 입력칸 첫 값으로 — 문단을 빈 줄로 잇는다. */
export function joinParagraphRange(paragraphs: readonly string[], range: ParagraphRange): string {
  return paragraphs.slice(range.start, range.end + 1).join(PARAGRAPH_SEPARATOR);
}

/** 지금 본문을 같은 방식으로 이은 값. 조립한 본문과 같으면 바뀐 것이 없다. */
export function joinChapterParagraphs(paragraphs: readonly string[]): string {
  return paragraphs.join(PARAGRAPH_SEPARATOR);
}

/** 직접 고치기를 시작한 순간의 장. 범위의 인덱스는 이 판의 문단을, `blockIds` 는 이 판의 문단마다 붙은 블록 id 를 가리킨다. */
export type ManualEditBase = {
  revisionId: string;
  paragraphs: readonly string[];
  blockIds: readonly string[];
  range: ParagraphRange;
};

/** 화면이 보고 있는 지금 판(화 응답의 `revision` 모양). */
export type ManualEditRevision = {
  id: string;
  paragraphs: readonly string[];
  blocks: readonly { id: string }[];
};

function isSameList(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((item, index) => item === b[index]);
}

/** 시작한 판 대신 지금 판을 기준으로 보내도 되는가 — 글도 블록 id 도 시작한 판과 같으면 이용자가 보고 고친 것과 같은
 * 판이다(삽화만 바꾼 판은 블록 id 를 그대로 잇는다). 같은 글이라도 블록 id 가 다르면(옛 판으로 되돌린 판) 시작한 판의 id 를
 * 실은 저장은 서버가 받지 않으므로 아니다. */
function canRebase(base: ManualEditBase, current: ManualEditRevision): boolean {
  const currentIds = current.blocks.map((block) => block.id);
  return isSameList(base.paragraphs, current.paragraphs) && isSameList(base.blockIds, currentIds);
}

/** 직접 고치는 사이 판이 바뀌어 이대로는 저장할 수 없는가. 같은 글·같은 블록의 새 판이면 그 판 위에 저장하므로 낡지 않았다. */
export function isManualEditStale(base: ManualEditBase, current: ManualEditRevision): boolean {
  return base.revisionId !== current.id && !canRebase(base, current);
}

/** 직접 고친 글을 저장 요청으로 만든다. 본문은 **시작한 판**의 문단으로 조립한다 — 지금 보이는 판으로 조립하면 같은
 * 인덱스가 새 판의 다른 문단을 가리키고, 이용자가 보지 못한 새 글을 서버가 그대로 받아 덮는다. 기준은 시작한 판이고, 그사이
 * 생긴 판이 같은 글·같은 블록이면(같은 탭·다른 탭의 삽화 조작) 그 판이다 — 아니면 서버가 충돌로 막는다.
 *
 * `blockIds` 는 본문 문단마다 이을 블록 id(새 문단은 `null`)다. 범위 밖 문단은 제자리 id 를 싣고, 범위 안은
 * `inheritBlockIds` 로 맞춘다. 싣지 않으면 서버가 글자로 맞추는데, 범위 가장자리에 바깥 문단과 같은 글을 새로 쓰면 바깥 문단
 * id 가 그 새 문단으로 옮겨 가 그 문단에 붙은 삽화가 엉뚱한 자리에 선다. */
export function toManualEditSave(
  base: ManualEditBase,
  draft: string,
  current: ManualEditRevision,
): { baseRevisionId: string; body: string; blockIds: (string | null)[]; isUnchanged: boolean } {
  const { paragraphs, blockIds, range } = base;
  const body = assembleChapterBody(paragraphs, range, draft);
  const rangeIds = inheritBlockIds(
    paragraphs.slice(range.start, range.end + 1),
    blockIds.slice(range.start, range.end + 1),
    splitChapterParagraphs(draft),
  );
  return {
    baseRevisionId: canRebase(base, current) ? current.id : base.revisionId,
    body,
    blockIds: [
      ...blockIds.slice(0, range.start),
      ...rangeIds,
      ...blockIds.slice(range.end + 1),
    ],
    isUnchanged: body === joinChapterParagraphs(paragraphs),
  };
}

/** 옛 문단·id 와 새 문단에서 새 문단마다 이을 id. 서버가 범위 편집에 쓰는 규칙과 같다 — 글이 같은 문단은 id 를 잇고, 바뀐
 * 구간마다 그 구간의 첫 새 문단이 첫 옛 id 를 잇고 나머지는 새 문단(`null`)이다. 문단 단위 최장 공통 부분열로 짝을 짓는다(같은
 * 글 문단이 여럿이면 서버와 다른 짝을 고를 수 있지만, 서버는 id 의 수·소속·겹침만 보아 둘 다 받는다). 입력칸 한 번의 범위라
 * 문단 수가 작아 표 하나로 충분하다. */
export function inheritBlockIds(
  oldParagraphs: readonly string[],
  oldIds: readonly string[],
  newParagraphs: readonly string[],
): (string | null)[] {
  const rows = oldParagraphs.length;
  const columns = newParagraphs.length;
  // 옛 i.. 와 새 j.. 의 최장 공통 부분열 길이 표(행 우선 한 줄 배열).
  const width = columns + 1;
  const lengths = new Array<number>((rows + 1) * width).fill(0);
  const lengthAt = (i: number, j: number) => lengths[i * width + j] ?? 0;
  for (let i = rows - 1; i >= 0; i -= 1) {
    for (let j = columns - 1; j >= 0; j -= 1) {
      lengths[i * width + j] =
        oldParagraphs[i] === newParagraphs[j] ? lengthAt(i + 1, j + 1) + 1 : Math.max(lengthAt(i + 1, j), lengthAt(i, j + 1));
    }
  }

  const ids: (string | null)[] = [];
  let i = 0;
  let j = 0;
  // 바뀐 구간의 시작점들. 구간 안 첫 새 문단이 첫 옛 id 를 잇는다.
  let gapOld = 0;
  let gapNew = 0;
  const closeGap = () => {
    for (let k = gapNew; k < j; k += 1) ids.push(k === gapNew && gapOld < i ? (oldIds[gapOld] ?? null) : null);
  };
  while (i < rows || j < columns) {
    if (i < rows && j < columns && oldParagraphs[i] === newParagraphs[j] && lengthAt(i, j) === lengthAt(i + 1, j + 1) + 1) {
      closeGap();
      ids.push(oldIds[i] ?? null);
      i += 1;
      j += 1;
      gapOld = i;
      gapNew = j;
    } else if (j < columns && (i >= rows || lengthAt(i, j + 1) >= lengthAt(i + 1, j))) {
      j += 1;
    } else {
      i += 1;
    }
  }
  closeGap();
  return ids;
}

/** 서버가 세는 방식의 글자 수 — 앞뒤 공백을 걷은 뒤 코드 포인트 수. `.length` 는 이모지를 2자로 센다. */
export function countChapterChars(text: string): number {
  return Array.from(text.trim()).length;
}

export type AiEditComparison = {
  /** 지금 본문에서 고른 문단들. */
  original: string[];
  /** 수정안에서 그 자리에 들어갈 문단들. 문단 수는 원래 범위와 다를 수 있다. */
  candidate: string[];
};

/** AI 수정안(장 전체 본문)에서 고른 범위 자리의 문단만 꺼낸다. 서버가 범위 밖 문단을 원본 그대로 앞뒤에 붙여
 * 수정안을 만들므로, 수정안 문단에서 앞 `start` 개와 뒤(원래 범위 뒤에 있던 문단 수)를 덜어 내면 바뀐 자리다.
 * 그 셈이 맞지 않는 본문(앞뒤가 겹칠 만큼 짧음)이 오면 수정안 전체를 후보로 보인다 — 무엇이 적용되는지 숨기지
 * 않는 쪽이다. */
export function toAiEditComparison(
  paragraphs: readonly string[],
  resultText: string,
  range: ParagraphRange,
): AiEditComparison {
  const original = paragraphs.slice(range.start, range.end + 1);
  const result = splitChapterParagraphs(resultText);
  const tailCount = Math.max(0, paragraphs.length - range.end - 1);
  const candidateEnd = result.length - tailCount;
  const candidate = candidateEnd > range.start ? result.slice(range.start, candidateEnd) : result;
  return { original, candidate };
}
