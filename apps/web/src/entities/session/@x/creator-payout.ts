// entities/creator-payout 전용 공개 API. 지급 신청 실패를 결과 갈래로 나눌 때 정지 403 을 가르고 같은 안내 문장을 쓴다.
export { isSuspendedError, SUSPENDED_ERROR_MESSAGE } from "../model/suspendedAccount";
