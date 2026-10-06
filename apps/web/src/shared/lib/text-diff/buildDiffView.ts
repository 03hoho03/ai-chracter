import { diffSentences, diffWords, type Change } from "diff";

/** 단어 단위 비교의 시간 상한(ms). 비슷한 5천 자 글은 수십 ms 안에 끝나지만 완전히 다른 글은 수 초가 걸려 화면이
 * 멈추므로, 넘으면 포기하고 문장 단위로 낮춘다. */
export const WORD_DIFF_TIMEOUT_MS = 200;
/** 문장 단위 비교의 시간 상한(ms). 이것도 넘으면 비교를 보여 주지 않는다 — 두 단계를 합쳐도 화면이 멈추는 시간은 이
 * 둘의 합을 넘지 않는다. */
export const SENTENCE_DIFF_TIMEOUT_MS = 200;

/** 시간 상한 안에 끝나지 않으면 `undefined` 를 돌려주는 비교 함수. */
export type DiffRunner = (before: string, after: string) => Change[] | undefined;

export type DiffRunners = { words: DiffRunner; sentences: DiffRunner };

export type DiffSegment = { kind: "equal" | "added" | "removed"; text: string };

/** 문단 단위 표시 묶음. 바뀐 문단은 하나씩 펼치고, 사이의 바뀌지 않은 문단은 한 덩어리로 접어 둘 수 있게 모은다. */
export type DiffBlock =
  | { kind: "changed"; segments: DiffSegment[] }
  | { kind: "unchanged"; paragraphs: string[] };

export type DiffView =
  | { status: "compared"; granularity: "word" | "sentence"; blocks: DiffBlock[]; changedParagraphCount: number }
  | { status: "tooLarge" };

// 한국어는 공백 단위가 어절이라 정규식 단어 나누기로는 조사·어미가 붙은 어절 전체가 바뀐 것으로 잡힌다. 브라우저의
// 한국어 단어 경계를 쓰면 바뀐 부분이 더 좁게 잡힌다.
const koreanWordSegmenter = new Intl.Segmenter("ko", { granularity: "word" });

export function createDiffRunners(
  wordTimeoutMs: number = WORD_DIFF_TIMEOUT_MS,
  sentenceTimeoutMs: number = SENTENCE_DIFF_TIMEOUT_MS,
): DiffRunners {
  return {
    words: (before, after) =>
      diffWords(before, after, { intlSegmenter: koreanWordSegmenter, timeout: wordTimeoutMs }),
    sentences: (before, after) => diffSentences(before, after, { timeout: sentenceTimeoutMs }),
  };
}

const defaultRunners = createDiffRunners();

// 문단 구분은 빈 줄(공백만 있는 줄 포함)이다. 저장된 본문은 문단을 빈 줄 하나로 잇는다.
const PARAGRAPH_SEPARATOR = /\n[ \t]*\n/g;

function toKind(change: Change): DiffSegment["kind"] {
  if (change.added) return "added";
  if (change.removed) return "removed";
  return "equal";
}

type Paragraph = { segments: DiffSegment[]; isChanged: boolean };

/** 문단 앞뒤 공백을 걷고 빈 조각을 버린다. 문단 사이 빈 줄 주변의 공백이 표시에 남지 않게 한다. */
function trimParagraph(paragraph: Paragraph): Paragraph {
  const segments = paragraph.segments.map((segment) => ({ ...segment }));
  const first = segments[0];
  if (first) first.text = first.text.trimStart();
  const last = segments.at(-1);
  if (last) last.text = last.text.trimEnd();
  return { segments: segments.filter((segment) => segment.text.length > 0), isChanged: paragraph.isChanged };
}

/**
 * 비교 결과를 문단으로 자른다. 문단 구분은 이어 붙인 글 전체에서 찾는다 — 빈 줄의 두 줄바꿈이 서로 다른 비교 조각에
 * 걸쳐 있어도 놓치지 않으려는 것이다. 구분 자체가 더해지거나 지워졌으면(문단을 나누거나 합쳤으면) 구분 앞 문단을
 * 바뀐 것으로 친다 — 구분 뒤 문단까지 치면 문단 하나를 끼워 넣었을 때 그 뒤의 그대로인 문단도 펼쳐진다.
 */
function splitParagraphs(changes: Change[]): Paragraph[] {
  const pieces = changes.map((change) => ({ kind: toKind(change), text: change.value }));
  const merged = pieces.map((piece) => piece.text).join("");
  const separators = [...merged.matchAll(PARAGRAPH_SEPARATOR)].map((match) => ({
    start: match.index,
    end: match.index + match[0].length,
  }));

  const paragraphs: Paragraph[] = [];
  let current: Paragraph = { segments: [], isChanged: false };
  let separatorIndex = 0;
  let offset = 0;

  for (const piece of pieces) {
    let cursor = 0;
    while (cursor < piece.text.length) {
      const absolute = offset + cursor;
      const separator = separators[separatorIndex];
      if (separator && absolute >= separator.start) {
        // 구분 안의 글자는 문단 내용이 아니다. 구분이 끝나는 곳까지 건너뛰고 새 문단을 연다.
        const skipEnd = Math.min(piece.text.length, separator.end - offset);
        if (piece.kind !== "equal") current.isChanged = true;
        cursor = skipEnd;
        if (offset + cursor >= separator.end) {
          paragraphs.push(current);
          current = { segments: [], isChanged: false };
          separatorIndex += 1;
        }
        continue;
      }
      const textEnd = separator ? Math.min(piece.text.length, separator.start - offset) : piece.text.length;
      const text = piece.text.slice(cursor, textEnd);
      current.segments.push({ kind: piece.kind, text });
      if (piece.kind !== "equal") current.isChanged = true;
      cursor = textEnd;
    }
    offset += piece.text.length;
  }
  paragraphs.push(current);
  return paragraphs.map(trimParagraph).filter((paragraph) => paragraph.segments.length > 0);
}

function toBlocks(paragraphs: Paragraph[]): DiffBlock[] {
  const blocks: DiffBlock[] = [];
  for (const paragraph of paragraphs) {
    if (paragraph.isChanged) {
      blocks.push({ kind: "changed", segments: paragraph.segments });
      continue;
    }
    const text = paragraph.segments.map((segment) => segment.text).join("");
    const previous = blocks.at(-1);
    if (previous?.kind === "unchanged") previous.paragraphs.push(text);
    else blocks.push({ kind: "unchanged", paragraphs: [text] });
  }
  return blocks;
}

function toView(changes: Change[], granularity: "word" | "sentence"): DiffView {
  const blocks = toBlocks(splitParagraphs(changes));
  const changedParagraphCount = blocks.filter((block) => block.kind === "changed").length;
  return { status: "compared", granularity, blocks, changedParagraphCount };
}

/**
 * 두 글의 차이를 문단 단위 표시 모델로 만든다. 단어 단위로 먼저 비교하고, 시간 상한을 넘으면 문장 단위로 낮추고,
 * 그것도 넘으면 `tooLarge` 를 돌려준다(화면은 "차이가 커서 비교를 보여 줄 수 없다"를 띄운다).
 * 비교 함수는 테스트가 시간에 기대지 않고 각 갈래를 고를 수 있게 주입받는다.
 */
export function buildDiffView(before: string, after: string, runners: DiffRunners = defaultRunners): DiffView {
  const words = runners.words(before, after);
  if (words) return toView(words, "word");
  const sentences = runners.sentences(before, after);
  if (sentences) return toView(sentences, "sentence");
  return { status: "tooLarge" };
}
