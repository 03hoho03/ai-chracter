// entities/creator-payout 전용 공개 API. 지급 신청 실패를 결과 갈래로 나눌 때 본인인증 403 을 가른다.
export { isIdentityVerificationRequiredError } from "../model/identityGate";
