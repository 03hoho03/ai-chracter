import { hasNovelErrorCode } from "@/entities/novel";

/** 카드 자리 저장이 실패했을 때 할 일. 대부분은 고정 토스트 하나로 알린다. 조용히 넘기는 것은 둘이다 —
 * 크기 초과(422)는 서버가 좌표를 실수로 다시 재서 생기는 드문 경우라 다시 해도 같고 이용자가 할 수 있는 일이 없으며,
 * 재동의(403)는 전역 재동의 모달이 맡는다. 둘 다 다음 저장이 다시 시도한다. */
export function toBoardLayoutSaveFailure(error: unknown): "skip" | "notify" {
  if (hasNovelErrorCode(error, "NOVEL_BOARD_LAYOUT_TOO_LARGE")) return "skip";
  if (hasNovelErrorCode(error, "LEGAL_RECONSENT_REQUIRED")) return "skip";
  return "notify";
}
