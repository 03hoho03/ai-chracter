import type { Emphasis, Nodes, Paragraph, PhrasingContent, Root, Strong, Text } from "mdast";
import type { Options } from "react-markdown";
import type { Plugin } from "unified";

import { assertNever } from "@/shared/lib/assertNever";

import {
  ESCAPED_STAR,
  RAW_STAR,
  RAW_UNDERSCORE,
  type Fence,
  type StarNeighbor,
  type StarToken,
  type StarTree,
  type WrapDepth,
  isDateLike,
  isFenceClose,
  openFence,
  pairStarRuns,
  protectEscapedStars,
  splitLineStart,
  startsWithContainerMarker,
  tokenizeStars,
} from "../model/chatNotationSyntax";

// 파서 확장 목록은 remark-parse 가 unified 의 Data 에 선언하는데, 이 앱은 remark-parse 를 직접 의존하지
// 않아(react-markdown 안에 들어 있다) 그 선언이 보이지 않는다. 여기서 쓰는 만큼만 선언한다.
declare module "unified" {
  // eslint-disable-next-line @typescript-eslint/consistent-type-definitions -- 모듈 보강은 interface 선언 병합으로만 된다
  interface Data {
    micromarkExtensions?: unknown[];
  }
}

type PhrasingParent = Paragraph | Emphasis | Strong;
type PreparedLine = { prefix: string; body: string; isCode: boolean; isQuote: boolean };

const LONE_STAR_LINE_PATTERN = /^ {0,3}\*[ \t]*$/;
// 한 문단의 별표·밑줄이 이보다 많으면 파서에게 강조를 맡기지 않는다. 파서는 겹친 강조를 겹 수의
// 제곱으로 느리게 읽고(5000겹에 4초), 겹친 강조 트리는 렌더러가 깊이만큼 재귀해 스택이 넘친다.
// 보통 채팅 문단은 수십 개다.
const MAX_PARSER_DELIMITERS = 500;

/**
 * 채팅에서 만들 요소는 문단·지문·강조·인용·코드·구분선·목록·줄바꿈뿐이다. 나머지 구문(제목·링크·
 * 이미지·HTML·정의·자동 링크·들여쓰기 코드)은 파서 단계에서 꺼서 요소가 생기지 않고 원문 글자가
 * 그대로 남게 한다. 렌더 단계에서 요소만 걸러 내면 링크 주소·`#`·HTML 내용처럼 글자까지 사라진다.
 * `텍스트\n---` 의 제목화(setext)도 꺼서 문단 + 구분선이 된다.
 */
const remarkChatSubset: Plugin<[], Root> = function () {
  const data = this.data();
  const extensions = data.micromarkExtensions ?? [];
  extensions.push({
    disable: {
      null: [
        "setextUnderline",
        "headingAtx",
        "codeIndented",
        "htmlFlow",
        "htmlText",
        "autolink",
        "labelStartImage",
        "labelStartLink",
        "definition",
      ],
    },
  });
  data.micromarkExtensions = extensions;
};

/**
 * `_` 강조는 `>_<`·`^_^` 같은 이모티콘을 깨뜨리므로 쓰지 않는다. 파서에서 끄면 `*` 강조까지 꺼지므로,
 * 원문에서 `_` 로 시작한 강조 노드만 찾아 표지를 글자로 되돌리고 안쪽 내용은 그대로 둔다.
 */
const remarkRevertUnderscoreEmphasis: Plugin<[], Root> = function () {
  return (tree, file) => {
    const source = String(file);
    forEachPhrasingParent(tree, (parent) => {
      parent.children = parent.children.flatMap((child) => unwrapUnderscoreEmphasis(child, source));
    });
  };
};

/**
 * 파서가 짝짓지 못하고 글자로 남긴 별표를 채팅 규칙(`pairStarRuns`)으로 다시 짝짓는다. 코드·목록 표지·
 * 구분선의 별표는 이미 글자 노드가 아니라서 자연히 빠진다.
 */
const remarkRescueStars: Plugin<[], Root> = function () {
  return (tree, file) => {
    const source = String(file);
    forEachPhrasingParent(tree, (parent) => {
      const trailing = parent.type === "paragraph" ? trailingWhitespaceNeighbor(parent, source) : "none";
      parent.children = toPhrasing(pairStarRuns(tokenizePhrasing(parent.children, trailing)));
    });
    restoreEscapedStars(tree);
  };
};

/** 채팅에서는 문단 안 한 줄 바꿈이 그대로 줄바꿈이어야 한다(CommonMark 는 공백으로 합친다). */
const remarkNewlineToBreak: Plugin<[], Root> = function () {
  return (tree) => {
    forEachPhrasingParent(tree, (parent) => {
      parent.children = parent.children.flatMap((child): PhrasingContent[] => {
        if (child.type !== "text" || !child.value.includes("\n")) return [child];
        return child.value.split(/\r?\n/).flatMap((part, index): PhrasingContent[] => {
          const pieces: PhrasingContent[] = index > 0 ? [{ type: "break" }] : [];
          if (part !== "") pieces.push({ type: "text", value: part });
          return pieces;
        });
      });
    });
  };
};

export const CHAT_MARKDOWN_OPTIONS = {
  remarkPlugins: [remarkChatSubset, remarkRevertUnderscoreEmphasis, remarkRescueStars, remarkNewlineToBreak],
  allowedElements: ["p", "em", "strong", "blockquote", "pre", "code", "hr", "ul", "ol", "li", "br"],
  unwrapDisallowed: true,
} satisfies Options;

/**
 * 파서에 넘기기 전 원문을 채팅 규칙에 맞게 다듬는다. 코드 블록 안은 건드리지 않는다.
 * - `\*` 를 짝짓기에서 빼기 위한 표식으로 바꾼다.
 * - 줄 머리(인용·목록 표지 뒤 포함) `>` 뒤에 공백이 없으면(`>_<`) 인용이 아니라 글자로 둔다.
 * - 날짜형 번호(`2026. 9. 29.`)의 첫 마침표를 이스케이프해 목록이 되지 않게 한다.
 * - 인용·목록 표지가 깊이 한도보다 깊게 겹치면 나머지 표지를 글자로 둔다.
 * - 인용 줄 바로 다음에 `>` 없는 줄이 오면 사이에 빈 줄을 넣어 인용을 끝낸다. 마크다운은 그 줄을 인용
 *   안으로 흡수하는데(lazy continuation), 장면 헤더 다음의 본문이 작고 흐린 인용 글씨가 되어 버린다.
 * - 별표·밑줄이 너무 많은 문단은 파서에게서 숨기고 별표 짝짓기에만 맡긴다.
 * - 끝의 단독 `*` 줄은 빈 목록이 되므로 지운다(스트리밍 중 막 도착한 별표도, 저장된 메시지도 같다).
 */
export function prepareChatMarkdownSource(content: string): string {
  let fence: Fence | undefined;
  const lines = protectEscapedStars(content)
    .split("\n")
    .map((line): PreparedLine => {
      if (fence) {
        if (isFenceClose(line, fence)) fence = undefined;
        return { prefix: "", body: line, isCode: true, isQuote: false };
      }
      fence = openFence(line);
      if (fence) return { prefix: "", body: line, isCode: true, isQuote: false };
      const { prefix, body, hasQuoteMarker } = splitLineStart(line);
      return { prefix, body: escapeLineStart(body), isCode: false, isQuote: hasQuoteMarker };
    })
    .flatMap((line, index, all): PreparedLine[] => {
      const previous = all[index - 1];
      const shouldEndQuote = previous?.isQuote === true && !line.isQuote && !line.isCode && line.body.trim() !== "";
      return shouldEndQuote ? [{ prefix: "", body: "", isCode: false, isQuote: false }, line] : [line];
    });

  for (let last = lines.at(-1); last && !last.isCode; last = lines.at(-1)) {
    const text = last.prefix + last.body;
    if (text.trim() !== "" && !LONE_STAR_LINE_PATTERN.test(text)) break;
    lines.pop();
  }
  hideDelimitersFromParser(lines);
  return lines.map((line) => line.prefix + line.body).join("\n");
}

function escapeLineStart(body: string): string {
  if (isDateLike(body)) return body.replace(/^(\s*\d{1,9})\./, "$1\\.");
  if (startsWithContainerMarker(body)) {
    return body
      .replace(/^( {0,3})(\d{1,9})([.)])/, "$1$2\\$3")
      .replace(/^( {0,3})([->+])/, "$1\\$2")
      .replace(/^( {0,3})\*/, `$1${ESCAPED_STAR}`);
  }
  return body.replace(/^( {0,3})>(?=\S)/, "$1\\>");
}

/** 빈 줄로 나뉜 문단마다 별표·밑줄 수를 세어, 너무 많으면 파서가 못 보는 표식으로 바꾼다. */
function hideDelimitersFromParser(lines: PreparedLine[]): void {
  let block: PreparedLine[] = [];
  const flush = () => {
    const count = block.reduce((sum, line) => sum + (line.body.match(/[*_]/g)?.length ?? 0), 0);
    if (count > MAX_PARSER_DELIMITERS) {
      for (const line of block) line.body = line.body.replaceAll("*", RAW_STAR).replaceAll("_", RAW_UNDERSCORE);
    }
    block = [];
  };
  for (const line of lines) {
    if (line.isCode || (line.prefix + line.body).trim() === "") flush();
    else block.push(line);
  }
  flush();
}

function isPhrasingParent(node: Nodes): node is PhrasingParent {
  return node.type === "paragraph" || node.type === "emphasis" || node.type === "strong";
}

/** 자식부터 방문한다 — 부모가 자식 배열을 바꿀 때 자식은 이미 처리가 끝나 있어야 한다. */
function forEachPhrasingParent(node: Nodes, visit: (parent: PhrasingParent) => void): void {
  if ("children" in node) {
    for (const child of node.children) forEachPhrasingParent(child, visit);
  }
  if (isPhrasingParent(node)) visit(node);
}

function unwrapUnderscoreEmphasis(node: PhrasingContent, source: string): PhrasingContent[] {
  if (node.type !== "emphasis" && node.type !== "strong") return [node];
  const start = node.position?.start.offset;
  if (start === undefined || source.charAt(start) !== "_") return [node];
  const marker = node.type === "strong" ? "__" : "_";
  return [textNode(marker), ...node.children, textNode(marker)];
}

function tokenizePhrasing(children: PhrasingContent[], trailing: StarNeighbor): StarToken<PhrasingContent>[] {
  const merged = mergeAdjacentText(unparseEmphasisAfterStarRun(children));
  return merged.flatMap((child, index): StarToken<PhrasingContent>[] => {
    if (child.type !== "text") return [{ kind: "content", value: child }];
    const after = index === merged.length - 1 ? trailing : neighborOf(merged[index + 1]);
    const value = child.value.replaceAll(RAW_STAR, "*");
    return tokenizeStars(value, neighborOf(merged[index - 1]), after).map((token) =>
      token.kind === "run" ? token : { kind: "content", value: textNode(token.value) },
    );
  });
}

/**
 * 파서가 짝지은 강조 바로 앞에 별표가 남아 있으면, 파서가 한 표지 런을 쪼개 반만 쓴 것이다
 * (`**굵게*` 를 `*` + 지문으로, `*그가 **"안 돼"**라고 했다*` 의 둘째 `**` 를 뒤 `*` 와 짝지어 읽는다).
 * 그 강조를 별표 글자로 되돌려 채팅 규칙이 처음부터 다시 짝짓게 한다. 그대로 두면 스트리밍 중
 * `**굵게`(굵게) → `**굵게*`(지문) → `**굵게**`(굵게)로 모양이 뒤집힌다.
 */
function unparseEmphasisAfterStarRun(children: PhrasingContent[]): PhrasingContent[] {
  return children.flatMap((child, index): PhrasingContent[] => {
    const previous = children[index - 1];
    if ((child.type !== "emphasis" && child.type !== "strong") || previous?.type !== "text") return [child];
    if (!previous.value.endsWith("*")) return [child];
    const marker = child.type === "strong" ? "**" : "*";
    return [textNode(marker), ...child.children, textNode(marker)];
  });
}

/**
 * 파서는 문단 끝 공백을 잘라 내므로 `별점 5* ` 의 별표는 뒤가 "없음"으로 보여 반쪽 표지로 지워진다.
 * 원문에서 문단 마지막 글자 바로 뒤를 확인해, 공백이었으면 공백으로 알려 준다(별표가 글자로 남는다).
 */
function trailingWhitespaceNeighbor(paragraph: Paragraph, source: string): StarNeighbor {
  const last = paragraph.children.at(-1);
  const end = last?.type === "text" ? last.position?.end.offset : undefined;
  if (end === undefined) return "none";
  const next = source.charAt(end);
  return next === " " || next === "\t" ? "space" : "none";
}

// 글자 노드는 이미 합쳐 두었으므로 이웃은 언제나 글자가 아닌 노드다.
function neighborOf(node: PhrasingContent | undefined): StarNeighbor {
  if (!node) return "none";
  if (node.type === "emphasis" || node.type === "strong") return "marker";
  if (node.type === "break") return "space";
  return "other";
}

function toPhrasing(tree: StarTree<PhrasingContent>): PhrasingContent[] {
  return tree.flatMap((node): PhrasingContent[] => {
    switch (node.kind) {
      case "content":
        return node.value.type === "text" && node.value.value === "" ? [] : [node.value];
      case "literal":
        return [textNode("*".repeat(node.length))];
      case "wrap":
        return [wrapPhrasing(node.depth, toPhrasing(node.children))];
      default:
        return assertNever(node);
    }
  });
}

function wrapPhrasing(depth: WrapDepth, children: PhrasingContent[]): Emphasis | Strong {
  switch (depth) {
    case 1:
      return { type: "emphasis", children };
    case 2:
      return { type: "strong", children };
    case 3:
      return { type: "emphasis", children: [{ type: "strong", children }] };
  }
}

function mergeAdjacentText(children: PhrasingContent[]): PhrasingContent[] {
  const merged: PhrasingContent[] = [];
  for (const child of children) {
    const last = merged.at(-1);
    if (child.type === "text" && last?.type === "text") last.value += child.value;
    else merged.push(child);
  }
  return merged;
}

function textNode(value: string): Text {
  return { type: "text", value };
}

function restoreEscapedStars(node: Nodes): void {
  if (node.type === "text") {
    node.value = node.value.replaceAll(ESCAPED_STAR, "*").replaceAll(RAW_STAR, "*").replaceAll(RAW_UNDERSCORE, "_");
  }
  // 코드 안의 `\*` 는 이스케이프가 아니라 원문 그대로다.
  if (node.type === "inlineCode" || node.type === "code") {
    node.value = node.value.replaceAll(ESCAPED_STAR, "\\*").replaceAll(RAW_STAR, "*").replaceAll(RAW_UNDERSCORE, "_");
  }
  if ("children" in node) for (const child of node.children) restoreEscapedStars(child);
}
