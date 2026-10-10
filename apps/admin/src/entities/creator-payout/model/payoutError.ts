import { apiErrorCode } from "@/shared/lib/api/client";

/**
 * 지급 처리·열람 실패를 셋으로 가른다.
 * - `stale`: 화면의 지급 건이 낡아 같은 처리를 다시 해도 같은 거부가 온다(이미 처리됨·없어짐·탈퇴 여부가 바뀜). 화면은
 *   다시 읽었으니 알리고 입력을 비운다.
 * - `input`: 운영자가 넣은 값이 서버 기준에 맞지 않는다(이체일·수취 정보). 입력을 살린 채 고치게 한다.
 * - `retry`: 서버·네트워크 실패나 설정 문제. 입력을 살린 채 알린다.
 */
export type CreatorPayoutFailure =
  | { kind: "stale"; message: string }
  | { kind: "input"; message: string }
  | { kind: "retry"; message: string };

const RETRY_MESSAGE = "처리하지 못했어요. 잠시 후 다시 시도해주세요.";

/** 서버가 `detail.code` 로 보내는 지급 거부 전부. 응답 code 는 OpenAPI 에 실리지 않아 여기서 문구와 짝짓는다. */
const FAILURE_BY_CODE: Record<string, CreatorPayoutFailure> = {
  CREATOR_PAYOUT_NOT_FOUND: { kind: "stale", message: "지급 건을 찾지 못했어요. 목록에서 다시 골라주세요." },
  CREATOR_PAYOUT_NOT_REQUESTED: {
    kind: "stale",
    message: "이미 처리된 지급이에요. 지금 상태를 다시 불러왔어요.",
  },
  CREATOR_PAYOUT_PAYEE_CHANGED: {
    kind: "stale",
    // 기록하려던 운영자가 이미 앞 계좌로 송금했을 수 있다 — 그대로 다시 기록하면 돈을 받지 않은 새 수취인으로 이체가
    // 남는다. 그래서 두 경우를 갈라 안내한다.
    message:
      "그 사이 다른 운영자가 수취 정보를 바꿨어요. 아직 이체하지 않았다면 새 수취 정보로 이체한 뒤 기록하고, 이미 앞 계좌로 보냈다면 여기서 기록하지 말고 먼저 확인한 뒤 개발 담당자에게 알려주세요.",
  },
  CREATOR_PAYOUT_PAYEE_WITHDRAWN: {
    kind: "stale",
    message: "수취인이 탈퇴해 반려할 수 없어요. 보류한 뒤 수취 정보를 바꿔 이체해주세요.",
  },
  CREATOR_PAYOUT_PAYEE_NOT_WITHDRAWN: {
    kind: "stale",
    message: "탈퇴하지 않은 회원의 지급이라 보류·수취 정보 교체를 할 수 없어요. 이체할 수 없으면 반려해주세요.",
  },
  CREATOR_PAYOUT_TRANSFER_DATE_INVALID: {
    kind: "input",
    message: "이체일은 신청일부터 오늘(한국 시각)까지만 넣을 수 있어요.",
  },
  CREATOR_PAYOUT_INFO_INVALID: {
    kind: "input",
    message: "수취 정보 형식이 맞지 않아요. 실명·주민등록번호 13자리·은행·계좌번호 6~20자리를 확인해주세요.",
  },
  CREATOR_PAYOUT_FOREIGNER_UNSUPPORTED: {
    kind: "input",
    message: "외국인등록번호로는 지급할 수 없어요.",
  },
  CREATOR_PAYOUT_RRN_MISMATCH: {
    kind: "input",
    message: "주민등록번호의 생년월일이 지금 수취인 정보와 달라요. 본인이 보낸 정보인지 확인해주세요.",
  },
  CREATOR_PAYOUT_UNAVAILABLE: {
    kind: "retry",
    message: "지급 정보 암호화 키가 설정되지 않아 저장할 수 없어요. 개발 담당자에게 알려주세요.",
  },
  // 이체 기록에서는 상세를 다시 읽으면 이체 기록이 숨겨진다(다시 해도 같은 거절) — 그래서 낡은 화면처럼 알린다.
  CREATOR_PAYOUT_INFO_UNREADABLE: {
    kind: "stale",
    message: "지급 정보를 복호화하지 못했어요(암호화 키 문제). 개발 담당자에게 알려주세요.",
  },
};

export function toCreatorPayoutFailure(error: unknown): CreatorPayoutFailure {
  const code = apiErrorCode(error);
  const failure = code !== null && Object.hasOwn(FAILURE_BY_CODE, code) ? FAILURE_BY_CODE[code] : undefined;
  return failure ?? { kind: "retry", message: RETRY_MESSAGE };
}
