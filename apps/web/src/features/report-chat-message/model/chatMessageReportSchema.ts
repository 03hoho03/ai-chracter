import type { components } from "@ai-character-chat/api-types";
import { z } from "zod";

export type ChatMessageReportRequest = components["schemas"]["ChatMessageReportCreateRequest"];
export type ChatMessageReportReason = ChatMessageReportRequest["reason"];

/** 서버 `ChatMessageReportCreateRequest.note` 의 최대 길이와 같은 값이다. */
export const CHAT_MESSAGE_REPORT_NOTE_MAX_LENGTH = 200;

/** 채팅 응답 신고 사유의 웹 라벨은 여기 한 벌뿐이다. 생성된 타입을 키로 받는 `Record` 라 서버가 사유를
 * 더하고 api-types 를 다시 만들면 라벨을 넣기 전까지 typecheck 가 깨진다. 작품·댓글 신고 사유와는
 * 값도 문구도 다른 별개 목록이라 그쪽 라벨과 합치지 않는다. */
export const CHAT_MESSAGE_REPORT_REASON_LABELS: Record<ChatMessageReportReason, string> = {
  inappropriate: "부적절·선정적",
  minor_safety: "아동·청소년 관련",
  hateful: "혐오·공격적",
  out_of_character: "캐릭터·설정 붕괴",
  repetitive: "반복·어색한 문장",
  broken: "깨짐·오류",
  other: "기타",
};

export function isChatMessageReportReason(value: string): value is ChatMessageReportReason {
  return value in CHAT_MESSAGE_REPORT_REASON_LABELS;
}

/** 목록·검증을 라벨 맵에서 도출한다 — 손으로 또 적으면 새 사유가 모달에서 조용히 빠진다. */
export const CHAT_MESSAGE_REPORT_REASONS = Object.keys(CHAT_MESSAGE_REPORT_REASON_LABELS).filter(isChatMessageReportReason);

/** 메모가 서버가 세는 방식 그대로 센 글자 수 — 앞뒤 공백을 잘라낸 뒤 코드 포인트 수. 공백 포함 길이를 보이면
 * "203/200" 인데 제출은 통과하고, `.length`(UTF-16)로 세면 이모지가 2자가 돼 서버가 받는 메모를 화면이 먼저
 * 막는다. 카운터와 아래 검증이 이 값을 함께 쓴다. */
export function countNoteLength(note: string): number {
  return Array.from(note.trim()).length;
}

export const chatMessageReportSchema = z.object({
  reason: z.enum(CHAT_MESSAGE_REPORT_REASONS, { message: "신고 사유를 선택해주세요" }),
  note: z
    .string()
    .trim()
    .refine((value) => countNoteLength(value) <= CHAT_MESSAGE_REPORT_NOTE_MAX_LENGTH, {
      message: `메모는 ${CHAT_MESSAGE_REPORT_NOTE_MAX_LENGTH}자 이내로 입력해주세요`,
    }),
});

export type ChatMessageReportFormValues = z.infer<typeof chatMessageReportSchema>;
