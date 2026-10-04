import { ChatMarkdown, USER_MESSAGE_FRAME } from "@/entities/chat-room";

import type { ConversationMessage } from "../model/toGuidePages";

type GuideConversationProps = {
  messages: ConversationMessage[];
};

/**
 * 채팅 화면 예시. 실제 채팅방과 같은 렌더러(`ChatMarkdown`)와 같은 사용자 메시지 틀로 그려서, 가이드가
 * 보여 주는 모양이 제작자가 미리보기·채팅에서 보게 될 모양과 같다. 메시지 사이는 채팅과 같은 `gap-6`
 * (한 메시지 안 문단 간격의 두 배)이다.
 *
 * 예시를 카드 면에 올려 가이드 본문과 가른다. 그래서 상태창 코드 블록은 `secondary` 면을 쓴다 — 기본
 * `bg-muted` 는 카드와 값이 같아 그 위에서 사라진다.
 */
export function GuideConversation({ messages }: GuideConversationProps) {
  return (
    <figure className="m-0 flex flex-col gap-3 rounded-xl border border-border bg-card p-4">
      <figcaption className="text-xs font-medium text-muted-foreground">채팅 화면 예시</figcaption>
      <div className="flex flex-col gap-6">
        {messages.map((message, index) => (
          // 원고에서 온 고정 목록이라 순서가 바뀌지 않는다.
          <div key={index} className={message.role === "user" ? USER_MESSAGE_FRAME : undefined}>
            <ChatMarkdown content={message.body} codeBlockSurface="secondary" />
          </div>
        ))}
      </div>
    </figure>
  );
}
