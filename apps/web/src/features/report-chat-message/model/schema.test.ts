import { describe, expect, it } from "vitest";

import { CHAT_MESSAGE_REPORT_NOTE_MAX_LENGTH, chatMessageReportSchema, countNoteLength } from "./schema";

describe("countNoteLength", () => {
  it("counts an emoji as one character", () => {
    expect(countNoteLength("😀가")).toBe(2);
  });

  it("leaves out the surrounding whitespace the server strips", () => {
    expect(countNoteLength("  가 나\n ")).toBe(3);
  });
});

describe("chatMessageReportSchema", () => {
  // 서버는 앞뒤 공백을 뗀 뒤 코드 포인트로 한도를 잰다 — UTF-16 으로 재면 이모지 200자를 400자로 보고 막는다.
  it("accepts a note of emoji at the limit and rejects one over it", () => {
    const note = "😀".repeat(CHAT_MESSAGE_REPORT_NOTE_MAX_LENGTH);
    expect(chatMessageReportSchema.safeParse({ reason: "other", note }).success).toBe(true);
    expect(chatMessageReportSchema.safeParse({ reason: "other", note: `${note}😀` }).success).toBe(false);
  });

  it("measures the note after trimming and returns the trimmed value", () => {
    const note = "가".repeat(CHAT_MESSAGE_REPORT_NOTE_MAX_LENGTH);
    const result = chatMessageReportSchema.safeParse({ reason: "other", note: `  ${note}  ` });
    expect(result.success).toBe(true);
    expect(result.data?.note).toBe(note);
  });
});
