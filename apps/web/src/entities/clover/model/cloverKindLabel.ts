/** `kind` → 한국어 라벨 맵. 어드민에도 같은 맵이 이미 있지만
 * (`apps/admin/src/entities/admin-user/model/labels.ts` `CLOVER_KIND_LABELS`) 별도 번들이라
 * 공유하지 않는 것이 결정이다 — web은 자기 사본을 갖는다.
 *
 * `CloverLedgerItem.kind`가 `Literal`이 아니라 `string`인 것과 같은 이유로(모델이 `Text`라 값이
 * 늘어도 마이그레이션·코드젠이 안 깨지게 한 것) 여기도 `Record<string, string>`이고, 모르는 키는
 * 호출부가 원문 그대로 보여준다(`?? kind` 폴백, admin `CLOVER_KIND_LABELS`와 같은 관례). BE
 * `CLOVER_KIND_CATEGORY`(`clover/router.py`)의 18종과 글자 단위로 대조했다. */
export const CLOVER_KIND_LABELS: Record<string, string> = {
  attendance_grant: "출석 지급",
  mission_grant: "미션 보상",
  admin_grant: "운영자 지급",
  chat_refund: "채팅 환불",
  image_refund: "이미지 환불",
  novelize_refund: "소설 환불",
  chat_spend: "채팅 사용",
  image_spend: "이미지 사용",
  novelize_spend: "소설 사용",
  expire_burn: "유효기간 소멸",
  admin_revoke: "운영자 회수",
  withdrawal_burn: "탈퇴 소멸",
  purchase_paid: "클로버 구매",
  purchase_bonus: "구매 보너스",
  purchase_revoke: "구매 취소 회수",
  purchase_restore: "구매 회수 복원",
  novel_read_spend: "노벨 소장",
  novel_read_refund: "노벨 삭제 환급",
};
