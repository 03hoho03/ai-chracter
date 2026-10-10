import type { components } from "@ai-character-chat/api-types";

export type BankCode = components["schemas"]["CreatorPayoutInfoView"]["bankCode"];

/** 지급 정보의 은행(금융결제원 3자리 코드 → 이름). 서버가 받는 코드 목록과 같아야 한다 — `Record` 라 서버 목록이 바뀌어
 * api-types 를 다시 만들면 타입 검사가 이 표를 고치라고 막는다. 선택 목록은 이 표의 순서대로 보인다(이용자가 많은
 * 은행을 앞에). */
export const BANK_LABELS: Record<BankCode, string> = {
  "004": "KB국민은행",
  "088": "신한은행",
  "020": "우리은행",
  "081": "하나은행",
  "011": "NH농협은행",
  "012": "지역 농·축협",
  "003": "IBK기업은행",
  "090": "카카오뱅크",
  "092": "토스뱅크",
  "089": "케이뱅크",
  "071": "우체국",
  "045": "새마을금고",
  "048": "신협",
  "007": "수협은행",
  "002": "KDB산업은행",
  "023": "SC제일은행",
  "027": "한국씨티은행",
  "031": "iM뱅크(대구은행)",
  "032": "부산은행",
  "039": "경남은행",
  "034": "광주은행",
  "037": "전북은행",
  "035": "제주은행",
  "050": "저축은행",
  "064": "산림조합",
};

export function isBankCode(value: string): value is BankCode {
  return Object.hasOwn(BANK_LABELS, value);
}

export const BANK_CODES: readonly BankCode[] = Object.keys(BANK_LABELS).filter(isBankCode);
