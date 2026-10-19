import { apiErrorCode } from "@/shared/lib/api/client";

/** 조치가 노벨 구매를 돌려주는 사이 새 구매가 들어와 서버가 조치 전체를 되돌린 409 인가. 다시 누르면 새 구매자까지
 * 함께 처리되므로, 이 실패는 모달·패널을 닫지 않고 입력을 남긴 채 다시 누르라고 말한다. */
export function isNovelRefundConflict(error: unknown): boolean {
  return apiErrorCode(error) === "NOVEL_REFUND_CONFLICT";
}

/** 그 409 의 문장. 노벨을 직접 조치했는지, 원작 작품을 조치해 그 작품으로 만든 노벨이 함께 걸렸는지로 갈린다. */
export const NOVEL_REFUND_CONFLICT_MESSAGE = {
  novel: "그사이 이 노벨을 새로 산 회원이 생겨 조치를 되돌렸어요. 다시 눌러 주세요.",
  content: "그사이 이 작품으로 만든 노벨을 새로 산 회원이 생겨 조치를 되돌렸어요. 다시 눌러 주세요.",
} as const;

/** 정책 스위치가 켜졌을 때 원작 작품의 이용제한·삭제가 더 하는 일. 작품 조치 확인에 덧붙인다. */
export const CONTENT_ACTION_NOVEL_REFUND_NOTE = "이 작품으로 만든 노벨을 산 회원에게는 쓴 클로버를 자동으로 돌려드려요.";

/** 정책 스위치가 켜졌을 때 노벨 이용제한이 더 하는 일. 노벨 신고 처리 확정 앞에 덧붙인다. */
export const NOVEL_RESTRICT_REFUND_NOTE = "이 노벨을 산 회원에게 쓴 클로버를 자동으로 돌려드려요.";
