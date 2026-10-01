import type { ChatMessageReportFormValues, ChatMessageReportRequest } from "./schema";

/** 폼값 → `POST /chat-rooms/{room_id}/messages/{message_id}/report` 본문. 메모는 스키마가 이미
 * trim 했으므로 비었으면 키를 아예 싣지 않는다 — "메모 없음"을 빈 문자열로 보내지 않는다. */
export function formToServer(values: ChatMessageReportFormValues): ChatMessageReportRequest {
  return values.note ? { reason: values.reason, note: values.note } : { reason: values.reason };
}
