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

/** 직접 고치기를 시작한 순간의 장. 범위의 인덱스는 이 판의 문단을 가리킨다. */
export type ManualEditBase = {
  revisionId: string;
  paragraphs: readonly string[];
  range: ParagraphRange;
};

/** 직접 고친 글을 저장 요청으로 만든다. 본문은 **시작한 판**의 문단으로 조립하고 그 판을 기준으로 보낸다 — 입력칸이
 * 열린 동안 다른 곳에서 판이 바뀌었으면 서버가 충돌로 막는다. 지금 보이는 판으로 조립하면 같은 인덱스가 새 판의 다른
 * 문단을 가리키고 기준도 새 판이라, 이용자가 보지 못한 새 글을 서버가 그대로 받아 덮는다. */
export function toManualEditSave(
  base: ManualEditBase,
  draft: string,
): { baseRevisionId: string; body: string; isUnchanged: boolean } {
  const body = assembleChapterBody(base.paragraphs, base.range, draft);
  return { baseRevisionId: base.revisionId, body, isUnchanged: body === joinChapterParagraphs(base.paragraphs) };
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
