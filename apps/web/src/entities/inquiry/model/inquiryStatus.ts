import type { components } from "@ai-character-chat/api-types";

export type InquiryStatus = components["schemas"]["InquiryStatus"];

export const INQUIRY_STATUS_LABEL: Record<InquiryStatus, string> = {
  pending: "대기",
  answered: "답변완료",
};
