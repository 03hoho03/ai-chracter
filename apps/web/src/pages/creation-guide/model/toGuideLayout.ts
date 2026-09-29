import { assertNever } from "@/shared/lib/assertNever";

import type { ManuscriptSegment } from "./parseManuscript";

export type ConversationMessage = { role: "character" | "user"; body: string };

export type GuideBlock =
  | { kind: "markdown"; source: string }
  | { kind: "conversation"; messages: ConversationMessage[] }
  | { kind: "field"; body: string };

export type GuideSection = { id: string; title: string; blocks: GuideBlock[] };

/** `lead` 는 첫 절 제목 앞의 들어가는 글이다(없으면 빈 배열). */
export type GuideLayout = { lead: GuideBlock[]; sections: GuideSection[] };

/**
 * 원고 조각을 화면 단위로 묶는다 — 제목마다 절 하나, 연달아 오는 `chat`·`chat-user` 예시는 대화 한 판.
 *
 * 대화를 묶는 이유: 실제 채팅처럼 메시지 사이 간격(한 메시지 안 문단 간격의 두 배)으로 이어져야 "여기서
 * 다른 사람의 말이 시작된다"가 읽힌다. 블록마다 따로 그리면 대화가 예시 상자 여러 개로 끊어져 보인다.
 */
export function toGuideLayout(segments: ManuscriptSegment[]): GuideLayout {
  const layout: GuideLayout = { lead: [], sections: [] };
  let blocks = layout.lead;

  for (const segment of segments) {
    switch (segment.kind) {
      case "heading": {
        const section: GuideSection = { id: segment.id, title: segment.text, blocks: [] };
        layout.sections.push(section);
        blocks = section.blocks;
        break;
      }
      case "markdown":
        blocks.push({ kind: "markdown", source: segment.source });
        break;
      case "example":
        switch (segment.exampleKind) {
          case "field":
            blocks.push({ kind: "field", body: segment.body });
            break;
          case "chat":
            appendMessage(blocks, { role: "character", body: segment.body });
            break;
          case "chat-user":
            appendMessage(blocks, { role: "user", body: segment.body });
            break;
          default:
            assertNever(segment.exampleKind);
        }
        break;
      default:
        assertNever(segment);
    }
  }

  return layout;
}

/** 바로 앞 블록이 대화면 거기에 잇고, 아니면 새 대화를 연다. */
function appendMessage(blocks: GuideBlock[], message: ConversationMessage) {
  const lastBlock = blocks.at(-1);
  if (lastBlock?.kind === "conversation") {
    lastBlock.messages.push(message);
  } else {
    blocks.push({ kind: "conversation", messages: [message] });
  }
}
