import {
  ESCAPED_STAR,
  type Fence,
  type StarToken,
  type StarTree,
  isFenceClose,
  openFence,
  pairStarRuns,
  protectEscapedStars,
  splitLineStart,
  tokenizeStars,
} from "./chatNotationSyntax";

const THEMATIC_BREAK_PATTERN = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
const INLINE_CODE_PATTERN = /(`[^`]+`)/;

/**
 * 대화 목록의 한 줄 미리보기용 평문을 만든다. 메시지 본문(ChatMarkdown)이 화면에 남기는 글자와 같게
 * 맞춘다 — 지문·굵게 별표, 인용 `> `, 목록 표지, 구분선, 코드 펜스 줄을 지우고, 코드 안 글자와
 * 채팅에서 요소로 만들지 않는 구문(`# 제목`, 링크, HTML)은 그대로 둔다. 별표는 렌더러와 같은 규칙으로
 * 문단 단위로 짝짓는다(짝이 줄을 넘을 수 있다). 결과는 한 칸 띄움으로 이은 한 줄이다.
 */
export function stripChatNotation(content: string): string {
  const pieces: string[] = [];
  let paragraph: string[] = [];
  const flushParagraph = () => {
    if (paragraph.length > 0) pieces.push(stripInline(paragraph.join("\n")));
    paragraph = [];
  };

  let fence: Fence | undefined;
  for (const line of content.split(/\r?\n/)) {
    if (fence) {
      if (isFenceClose(line, fence)) fence = undefined;
      else pieces.push(line);
      continue;
    }
    fence = openFence(line);
    if (fence || THEMATIC_BREAK_PATTERN.test(line)) {
      flushParagraph();
      continue;
    }
    const { body, hasListMarker } = splitLineStart(line);
    // 목록 항목은 새 문단이다. 인용 표지만 붙은 줄은 앞 줄과 같은 문단이다(렌더러도 이어 붙인다).
    if (hasListMarker || body.trim() === "") flushParagraph();
    if (body.trim() !== "") paragraph.push(body);
  }
  flushParagraph();
  return pieces.join(" ").replace(/\s+/g, " ").trim();
}

function stripInline(paragraph: string): string {
  // 인라인 코드 안은 글자 그대로이고, 짝짓기에는 글자가 아닌 덩어리 하나로 참여한다.
  const tokens = protectEscapedStars(paragraph)
    .split(INLINE_CODE_PATTERN)
    .flatMap((segment, index, segments): StarToken<string>[] => {
      if (index % 2 === 1) return [{ kind: "content", value: segment.slice(1, -1).replaceAll(ESCAPED_STAR, "\\*") }];
      const before = index > 0 ? "other" : "none";
      const after = index < segments.length - 1 ? "other" : "none";
      return tokenizeStars(segment, before, after).map((token) =>
        token.kind === "run" ? token : { kind: "content", value: unescapeText(token.value) },
      );
    });
  return flatten(pairStarRuns(tokens));
}

function unescapeText(text: string): string {
  return text.replace(/\\([!-/:-@[-`{-~])/g, "$1").replaceAll(ESCAPED_STAR, "*");
}

function flatten(tree: StarTree<string>): string {
  return tree
    .map((node) => {
      if (node.kind === "content") return node.value;
      if (node.kind === "literal") return "*".repeat(node.length);
      return flatten(node.children);
    })
    .join("");
}
