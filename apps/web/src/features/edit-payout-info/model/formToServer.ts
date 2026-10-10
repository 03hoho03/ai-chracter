import type { components } from "@ai-character-chat/api-types";

import { stripSeparators, type PayoutInfoSubmitValues } from "./schema";

export type PutPayoutInfoRequest = components["schemas"]["PutPayoutInfoRequest"];

/** 검증을 통과한 값을 서버 요청으로. 실명의 앞뒤 공백과 숫자 칸의 하이픈·공백을 뺀다. 동의는 체크해야 검증을 통과하므로
 * 언제나 `true` 다. */
export function formToServer(values: PayoutInfoSubmitValues): PutPayoutInfoRequest {
  return {
    legalName: values.legalName.trim(),
    rrn: stripSeparators(values.rrn),
    bankCode: values.bankCode,
    accountNumber: stripSeparators(values.accountNumber),
    agreed: true,
  };
}
