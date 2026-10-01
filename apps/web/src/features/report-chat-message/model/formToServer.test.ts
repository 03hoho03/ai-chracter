import { describe, expect, it } from "vitest";

import { formToServer } from "./formToServer";
import { CHAT_MESSAGE_REPORT_NOTE_MAX_LENGTH, chatMessageReportSchema, countNoteLength } from "./schema";

// 화면 제출과 같은 경로(스키마 파싱 → 본문 변환)로 확인한다 — trim 은 스키마가, 빈 메모 생략은 변환이 한다.
function toBody(raw: unknown) {
  return formToServer(chatMessageReportSchema.parse(raw));
}

describe("chat message report body", () => {
  it("sends the reason with the trimmed note", () => {
    expect(toBody({ reason: "out_of_character", note: "  갑자기 존댓말을 써요  " })).toEqual({
      reason: "out_of_character",
      note: "갑자기 존댓말을 써요",
    });
  });

  it("omits the note key when the note is empty or only spaces", () => {
    expect(toBody({ reason: "broken", note: "" })).toEqual({ reason: "broken" });
    expect(toBody({ reason: "other", note: "   \n " })).toEqual({ reason: "other" });
  });

  it("rejects a missing reason and a note over the limit", () => {
    expect(chatMessageReportSchema.safeParse({ note: "" }).success).toBe(false);
    expect(
      chatMessageReportSchema.safeParse({ reason: "other", note: "가".repeat(CHAT_MESSAGE_REPORT_NOTE_MAX_LENGTH + 1) })
        .success,
    ).toBe(false);
    expect(
      chatMessageReportSchema.safeParse({ reason: "other", note: "가".repeat(CHAT_MESSAGE_REPORT_NOTE_MAX_LENGTH) })
        .success,
    ).toBe(true);
  });

  // 카운터가 한도 안이라고 보이면 제출도 통과하고, 넘었다고 보이면 막혀야 한다 — 앞뒤 공백이 있어도.
  it("counts the note on the same trimmed basis the limit uses", () => {
    const atLimit = `  ${"가".repeat(CHAT_MESSAGE_REPORT_NOTE_MAX_LENGTH)}\n `;
    const overLimit = `  ${"가".repeat(CHAT_MESSAGE_REPORT_NOTE_MAX_LENGTH + 1)} `;
    expect(countNoteLength(atLimit)).toBe(CHAT_MESSAGE_REPORT_NOTE_MAX_LENGTH);
    expect(chatMessageReportSchema.safeParse({ reason: "other", note: atLimit }).success).toBe(true);
    expect(countNoteLength(overLimit)).toBe(CHAT_MESSAGE_REPORT_NOTE_MAX_LENGTH + 1);
    expect(chatMessageReportSchema.safeParse({ reason: "other", note: overLimit }).success).toBe(false);
  });
});
