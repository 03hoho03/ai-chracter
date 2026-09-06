import type { components } from "@ai-character-chat/api-types";

export const SIGNUP_METHOD_LABELS: Record<components["schemas"]["AdminUserDetailResponse"]["signupMethod"], string> = {
  google: "구글",
  email: "이메일",
};

/** `AdminUserActionLogItem.actionType`은 enum이 아니라 자유 문자열이다(user-warn/user-suspend/
 * user-unsuspend/restrict/delete/lift-restriction/reject 등, 작품 직접 조치와 유저 조치가 같은
 * 로그 테이블을 쓴다). 여기 없는 값은 호출부가 원문 그대로 보여준다(Record<string,string> 인덱싱은
 * noUncheckedIndexedAccess로 `string | undefined`라 `??` 폴백이 강제된다). */
export const ACTION_TYPE_LABELS: Record<string, string> = {
  "user-warn": "경고",
  "user-suspend": "정지",
  "user-unsuspend": "정지 해제",
  restrict: "이용제한 부과",
  delete: "삭제",
  "lift-restriction": "이용제한 해제",
  reject: "반려",
};
