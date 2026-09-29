export type TextSelection = {
  text: string;
  selectionStart: number;
  selectionEnd: number;
};

const MARKER = "*";

// 빈 줄(공백만 있는 줄 포함). 별표 짝은 이 경계를 넘지 못한다. 캡처 그룹이라 split 결과에 경계가 남는다.
const PARAGRAPH_BREAK = /(\n[ \t]*\n)/;

/**
 * 입력창에 지문 표시(`*…*`)를 넣거나 뺀다.
 * - 고른 글이 없으면 별표 한 쌍을 넣고 캐럿을 그 사이에 둔다 — 바로 지문을 쓰기 시작할 수 있다.
 * - 고른 글이 있으면 별표로 감싸고 캐럿을 닫는 별표 뒤로 옮긴다. 선택을 그대로 두면 이어서 치는 글자가
 *   방금 감싼 글을 통째로 덮어쓴다(모바일에서 특히 쉽게 일어난다).
 * - 고른 글이 이미 지문이면(별표까지 골랐든 안쪽만 골랐든) 별표를 벗기고 그 글을 고른 채로 둔다.
 *   굵게(`**`)는 지문이 아니므로 벗기지 않는다.
 * - 고른 범위 양끝의 공백은 별표 밖에 남긴다. `* 끄덕였다*` 처럼 별표가 공백에 붙으면 지문으로 읽히지 않는다.
 * - 빈 줄을 넘는 선택은 문단마다 따로 감싼다. 이미 지문인 문단은 그대로 두고(다시 감싸면 굵게가 된다),
 *   모든 문단이 지문이면 전부 벗긴다.
 */
export function insertNarrationMarker({ text, selectionStart, selectionEnd }: TextSelection): TextSelection {
  const from = Math.min(selectionStart, selectionEnd);
  const to = Math.max(selectionStart, selectionEnd);
  const selected = text.slice(from, to);
  const parts = selected.split(PARAGRAPH_BREAK);
  const paragraphs = parts.filter((part, index) => index % 2 === 0 && part.trim() !== "");

  if (paragraphs.length === 0) {
    const caret = to + MARKER.length;
    return { text: text.slice(0, to) + MARKER + MARKER + text.slice(to), selectionStart: caret, selectionEnd: caret };
  }
  if (paragraphs.length === 1) return toggleSingle(text, from, selected);

  const shouldUnwrapAll = paragraphs.every((paragraph) => isNarration(paragraph.trim()));
  const replaced = parts
    .map((part, index) => {
      const body = part.trim();
      if (index % 2 === 1 || body === "") return part;
      const bodyStart = part.indexOf(body);
      return part.slice(0, bodyStart) + toggleParagraph(body, shouldUnwrapAll) + part.slice(bodyStart + body.length);
    })
    .join("");
  const leading = replaced.length - replaced.trimStart().length;
  const end = from + replaced.trimEnd().length;
  return {
    text: text.slice(0, from) + replaced + text.slice(to),
    selectionStart: shouldUnwrapAll ? from + leading : end,
    selectionEnd: end,
  };
}

function toggleParagraph(body: string, shouldUnwrap: boolean): string {
  if (shouldUnwrap) return body.slice(1, -1);
  return isNarration(body) ? body : MARKER + body + MARKER;
}

function toggleSingle(text: string, from: number, selected: string): TextSelection {
  const body = selected.trim();
  const bodyStart = from + selected.indexOf(body);
  const bodyEnd = bodyStart + body.length;

  if (isNarration(body)) {
    return {
      text: text.slice(0, bodyStart) + body.slice(1, -1) + text.slice(bodyEnd),
      selectionStart: bodyStart,
      selectionEnd: bodyEnd - MARKER.length * 2,
    };
  }
  if (isLoneMarkerAt(text, bodyStart - 1) && isLoneMarkerAt(text, bodyEnd)) {
    return {
      text: text.slice(0, bodyStart - 1) + body + text.slice(bodyEnd + 1),
      selectionStart: bodyStart - 1,
      selectionEnd: bodyEnd - 1,
    };
  }
  const caret = bodyEnd + MARKER.length * 2;
  return {
    text: text.slice(0, bodyStart) + MARKER + body + MARKER + text.slice(bodyEnd),
    selectionStart: caret,
    selectionEnd: caret,
  };
}

/** 양끝이 단독 별표인 글(`*…*`). 굵게(`**…**`)는 아니다. */
function isNarration(body: string): boolean {
  return body.length >= 3 && body.startsWith(MARKER) && body.endsWith(MARKER) && body[1] !== MARKER && body.at(-2) !== MARKER;
}

/** `index` 자리가 별표이고 양옆이 별표가 아니다(굵게의 절반이 아니다). */
function isLoneMarkerAt(text: string, index: number): boolean {
  return text[index] === MARKER && text[index - 1] !== MARKER && text[index + 1] !== MARKER;
}
