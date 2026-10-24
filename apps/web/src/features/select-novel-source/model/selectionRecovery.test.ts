import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { toSelectionRecovery } from "./selectionRecovery";

function apiError(status: number, code: string) {
  return new ApiErrorObject({ status, message: "x", detail: { code } });
}

const NOTHING = { resetEdits: false, refetchSelection: false, refetchMessages: false, refetchPricing: false };

describe("toSelectionRecovery", () => {
  // 다른 탭이 먼저 저장했다 — 이 화면의 고침은 낡은 판 위에 있어 그대로 보내면 같은 409 를 되풀이한다.
  it("판 충돌은 고친 것을 버리고 선택을 다시 받는다", () => {
    expect(toSelectionRecovery(apiError(409, "NOVEL_SOURCE_SELECTION_CONFLICT"))).toEqual({
      ...NOTHING,
      resetEdits: true,
      refetchSelection: true,
    });
  });

  // 초안은 서버에 남아 있다. 다시 받으면 바뀐 구간 표시가 오고, 다시 승인하면 지금 원문으로 저장한 뒤 승인한다.
  it("원문 변경은 고친 것을 두고 선택과 대화를 다시 받는다", () => {
    expect(toSelectionRecovery(apiError(409, "NOVEL_SOURCE_SELECTION_SOURCE_CHANGED"))).toEqual({
      ...NOTHING,
      refetchSelection: true,
      refetchMessages: true,
    });
  });

  it.each(["NOVEL_SOURCE_MESSAGE_NOT_FOUND", "NOVEL_SOURCE_SECTION_INVALID", "NOVEL_SOURCE_SECTION_OUT_OF_RANGE"])(
    "%s 는 지금 대화와 어긋난 고침이라 버리고 둘 다 다시 받는다",
    (code) => {
      expect(toSelectionRecovery(apiError(422, code))).toEqual({
        ...NOTHING,
        resetEdits: true,
        refetchSelection: true,
        refetchMessages: true,
      });
    },
  );

  // 그사이 화가 생겼다. 고친 것은 두고 잠금만 새로 받는다 — 잠긴 턴은 화면이 담기로 보내지 않는다.
  it("잠긴 구간 거절은 선택만 다시 받는다", () => {
    expect(toSelectionRecovery(apiError(422, "NOVEL_SOURCE_SECTION_LOCKED"))).toEqual({ ...NOTHING, refetchSelection: true });
  });

  it("스위치가 꺼졌으면 가격을 다시 받아 구성 화면을 거둔다", () => {
    expect(toSelectionRecovery(apiError(404, "NOVEL_OUTLINE_FLOW_DISABLED"))).toEqual({ ...NOTHING, refetchPricing: true });
  });

  it.each([
    apiError(422, "NOVEL_SOURCE_SELECTION_EMPTY"),
    apiError(500, "SOMETHING"),
    new Error("network"),
  ])("그 밖의 실패는 아무것도 다시 받지 않는다 (%#)", (error) => {
    expect(toSelectionRecovery(error)).toEqual(NOTHING);
  });
});
