import type { components } from "@ai-character-chat/api-types";

import { formatKstDate } from "@/shared/lib/time/formatKstDate";

export type LegalChangeItem = components["schemas"]["LegalChangeItem"];

/**
 * 누적 변경 안내에 넣을 판들 — 회원이 마지막으로 동의한 판들 가운데 **가장 오래된 판보다 뒤에** 시행된 판 전부다.
 *
 * `items` 는 `GET /legal/{kind}/changes` 의 목록(시행 순서, 최신 판이 먼저)이다. 판의 앞뒤를 버전 문자열로 비교하면 같은 날
 * 재게시한 `2026-10-18.10` 이 `2026-10-18.2` 앞으로 가므로, 목록 안의 위치로만 정한다(뒤에 있을수록 오래된 판).
 *
 * 동의한 판이 하나라도 없거나(null) 목록에서 찾지 못하면 기준이 없으므로 전부를 준다 — 서버가 모르는 `since` 를 받을 때와 같은
 * 규칙이다. 모르는 판을 기준으로 아무것도 안 보이는 것보다 전부 보이는 쪽이 안전하다.
 */
export function selectChangesSinceOldestConsent(
  items: readonly LegalChangeItem[],
  consentedVersions: readonly (string | null)[],
): LegalChangeItem[] {
  let oldestIndex = -1;
  for (const version of consentedVersions) {
    const index = version === null ? -1 : items.findIndex((item) => item.version === version);
    if (index === -1) return [...items];
    oldestIndex = Math.max(oldestIndex, index);
  }
  if (oldestIndex === -1) return [...items];
  return items.slice(0, oldestIndex);
}

/** 판 하나의 변경 안내를 화면에 그릴 모양. `notice` 가 null 이면 그 판은 안내가 비어 있다(공백만 있는 안내도 빈 것으로 본다). */
export type ChangeNoticeEntry = {
  version: string;
  /** 한국 시각 `YYYY.MM.DD`. */
  effectiveDate: string;
  notice: string | null;
};

export function toChangeNoticeEntries(items: readonly LegalChangeItem[]): ChangeNoticeEntry[] {
  return items.map((item) => ({
    version: item.version,
    effectiveDate: formatKstDate(item.effectiveAt),
    notice: item.changeNotice !== null && item.changeNotice.trim() !== "" ? item.changeNotice : null,
  }));
}
