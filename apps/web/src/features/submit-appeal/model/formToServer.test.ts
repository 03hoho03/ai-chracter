import { describe, expect, it } from "vitest";

import { formToServer } from "./formToServer";
import { SUBMIT_APPEAL_SCHEMA } from "./submitAppealSchema";

// 화면 제출과 같은 경로(스키마 파싱 → 본문 변환)로 확인한다 — 공백 걷기는 스키마가, 대상 id 모으기는 변환이 한다.
function toBody(raw: unknown, target: Parameters<typeof formToServer>[1]) {
  return formToServer(SUBMIT_APPEAL_SCHEMA.parse(raw), target);
}

describe("appeal body", () => {
  it("sends a publish rejection with its rejection id and the trimmed reason", () => {
    expect(toBody({ reasonText: "  다시 봐 주세요 \n" }, { kind: "publish-rejection", rejectionId: "r-1" })).toEqual({
      targetKind: "publish-rejection",
      targetId: "r-1",
      reasonText: "다시 봐 주세요",
    });
  });

  it("sends a moderation action with its action id", () => {
    expect(toBody({ reasonText: "오해예요" }, { kind: "moderation-action", actionId: "a-1" })).toEqual({
      targetKind: "moderation-action",
      targetId: "a-1",
      reasonText: "오해예요",
    });
  });

  it("rejects a reason that is empty after trimming", () => {
    expect(SUBMIT_APPEAL_SCHEMA.safeParse({ reasonText: "  \n " }).success).toBe(false);
  });
});
