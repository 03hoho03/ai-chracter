import { formatCloverExpiryNotice, type CloverPolicyValues } from "@/entities/clover";
import { CONTACT_EMAIL } from "@/shared/config/site";

import { formatTrialSentence } from "./trialSentence";

/** 클로버 충전 화면의 정책 문장.
 *
 * 숫자(유효기간 햇수·전액 환불 날수·그 뒤 환불 비율)는 상품 응답의 `policy` 에서 받고 여기 적지 않는다. 반면 문장 자체는
 * 정책 문장이라 여기 적고, 같은 문장이 이용약관과 환불정책(둘 다 DB 게시본)에도 있다 — 셋 중 하나를 고치면 나머지와 함께
 * 맞춘다. 구매 조건의 요약 문장(`PURCHASE_CONDITION_SENTENCES`)도 아래 안내 문장들과 같은 사실을 줄여 말하므로 함께 맞춘다.
 *
 * "만 19세" 는 줄바꿈 없는 공백으로 잇는다 — 숫자와 "세" 가 두 줄로 갈리지 않게. */

/** 구매 조건 — 결제 직전 판단에 드는 것만. 구매 자격 문장은 결제가 켜져 있을 때만 싣는다(꺼져 있으면 살 수 없다는
 * 말이 먼저다). 자격은 서버의 주문 생성 판정 그대로다 — 본인인증은 나이를 확인하는 유일한 수단이라 미인증 회원 게이트
 * 스위치와 무관하게 늘 필요하고, 그 뒤 만 19세 미만을 막는다. 그래서 게이트 값으로 가르지 않는다. */
export const PURCHASE_CONDITION_SENTENCES = {
  vat: "가격은 부가세 포함이에요.",
  eligibility: "휴대폰 본인인증을 마친 만 19세 이상 회원만 살 수 있어요.",
  ageRestricted: "클로버는 만 19세 이상만 구매할 수 있어요.",
  bonusRefund: "환불할 때는 이미 쓴 보너스 클로버만큼 빼고 돌려드려요.",
} as const;

/** "유효기간과 사용 순서" 안내. `attendanceEnabled` 는 공개 가격 응답의 출석판 스위치다(못 받았으면 꺼짐). 출석판과 같은
 * 순간 이용약관·환불정책 새 게시본이 시행되므로, 출석 클로버를 말하는 두 문장은 스위치로 갈린다. */
export function formatValiditySentences(policy: CloverPolicyValues, attendanceEnabled = false): string[] {
  return [
    `유료 클로버와 보너스 클로버는 구매일로부터 ${policy.purchaseValidityYears}년 동안 쓸 수 있어요.`,
    formatCloverExpiryNotice(attendanceEnabled),
    "클로버는 무료, 보너스, 유료 순서로 쓰여요. 무료 클로버는 환불되지 않아요.",
    // 이 문장은 이용약관·환불정책 게시본의 같은 문장과 맞춰 둔 것이다. 꺼짐 문장은 지금 게시본, 켜짐 문장은 출석판과
    // 같은 순간 시행되는 새 게시본의 짝이다 — 화면에서만 고치면 게시본과 갈리므로 게시본을 개정할 때 함께 고친다.
    attendanceEnabled
      ? "미션 클로버와 출석 클로버는 휴대폰 본인인증을 마친 회원에게만 지급돼요."
      : "본인인증 기능이 열리면, 미션 클로버는 휴대폰 본인인증을 마친 회원에게만 지급돼요.",
  ];
}

/** "청약철회와 환불" 안내. 결제 전에 먼저 써 볼 수 있다는 문장은 출석판 스위치·게이트 스위치·무료 대화 수로 갈린다
 * (`formatTrialSentence`). */
export function formatRefundSentences(
  policy: CloverPolicyValues,
  identityGateEnabled: boolean,
  dailyFreeChatTurns: number,
  attendanceEnabled = false,
): string[] {
  return [
    `결제일로부터 ${policy.fullRefundDays}일 안에는 쓰지 않은 유료 클로버를 전액 돌려받을 수 있어요. 이미 쓴 보너스 클로버만큼은 빼고 돌려드려요.`,
    `${policy.fullRefundDays}일이 지나도 남은 유료 클로버를 환불받을 수 있어요. 이때도 이미 쓴 보너스 클로버만큼은 빼고, 그 금액의 ${policy.reducedRefundPercent}%를 돌려드려요.`,
    "이미 쓴 클로버는 청약철회할 수 없어요. 클로버는 쓰는 즉시 기능 이용에 제공되기 때문이에요.",
    formatTrialSentence(identityGateEnabled, dailyFreeChatTurns, attendanceEnabled),
    "보너스 클로버는 따로 환불되지 않아요. 유료 클로버를 환불하면 그 구매로 받은 보너스 클로버 중 남은 것은 회수돼요.",
    "탈퇴하면 남은 클로버가 모두 사라져요. 남은 유료 클로버는 탈퇴하기 전에 환불을 신청해주세요.",
    `이용이 정지된 동안에도 ${CONTACT_EMAIL}로 환불을 신청할 수 있어요.`,
  ];
}

/** "미성년자 결제" 안내. */
export const MINOR_PAYMENT_SENTENCE =
  "클로버는 만 19세 이상만 살 수 있어요. 그래도 미성년자가 법정대리인의 동의 없이 결제했다면 본인이나 법정대리인이 취소할 수 있어요. 다만 성년자이거나 법정대리인이 동의한 것처럼 속였거나, 용돈처럼 법정대리인이 쓰도록 허락한 돈의 범위에서 결제했다면 취소할 수 없어요.";
