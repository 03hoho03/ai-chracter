import type { ChatMessage } from "../api/chatStream";

/**
 * 사용자 메시지를 고쳐 저장하면 지워질 메시지 수 — 고친 메시지 뒤에 있는 메시지 전부(바로 다음 답 포함)다.
 * 서버는 고친 메시지 뒤를 모두 잘라 내고 새 답을 받으므로 화면에 받아 둔 목록으로 센다. 고친 메시지는 늘 화면에
 * 있어 그 뒤도 함께 받아 와 있다. 목록이 낡아 실제보다 적게 셀 수는 있다. 목록에 없는 id 면 0 이다.
 */
export function countMessagesAfter(messages: readonly ChatMessage[], messageId: string): number {
  const index = messages.findIndex((message) => message.id === messageId);
  return index === -1 ? 0 : messages.length - 1 - index;
}

/**
 * 사용자 메시지를 고치면 지워질 AI 응답 수. 서버는 그만큼 턴 수를 줄인 뒤 새 턴을 하나 더하므로 화면도 같은 수로 센다.
 * 목록에 없는 id 면 0 이다.
 */
export function countRepliesAfter(messages: readonly ChatMessage[], messageId: string): number {
  const index = messages.findIndex((message) => message.id === messageId);
  if (index === -1) return 0;
  return messages.slice(index + 1).filter((message) => message.role === "assistant").length;
}

/**
 * 수정 저장 전에 지워질 대화를 알리고 확인받을지. 하나만 지워지면 그것은 고친 말에 대한 바로 그 답이라 새 답으로
 * 바뀌는 것이 수정의 뜻 그대로다 — 그 너머까지 지워질 때만 묻는다.
 */
export function shouldConfirmEditTruncation(removedCount: number): boolean {
  return removedCount >= 2;
}
