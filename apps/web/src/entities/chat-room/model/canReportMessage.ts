import { z } from "zod";

import type { ChatMessage } from "../api/chatStream";

const serverMessageIdSchema = z.uuid();

// 채팅 응답 신고를 붙일 수 있는 메시지인가. 신고는 서버에 저장된 AI 응답의 id 로 요청하므로
// 두 조건이 다 필요하다 — 사용자 메시지는 신고 대상이 아니고(서버가 400 으로 거절한다), 화면이
// 임시로 만든 버블(`"streaming"`·`"ending-epilogue"`)은 저장된 행이 없어 요청할 id 가 없다.
// 저장된 행의 id 는 UUID 이고 임시 버블의 id 는 아니라서 형식으로 가른다.
// 빌더 미리보기는 이 판정으로 못 거른다 — 미리보기 응답 id 도 UUID 지만 DB 에 저장되지 않는다.
// 그래서 미리보기 화면은 이 함수를 쓰지 않고 신고 콜백 자체를 넘기지 않는다.
export function canReportMessage(message: Pick<ChatMessage, "id" | "role">): boolean {
  return message.role === "assistant" && serverMessageIdSchema.safeParse(message.id).success;
}
