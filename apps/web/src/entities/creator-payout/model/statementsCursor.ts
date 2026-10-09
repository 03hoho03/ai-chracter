import type { components } from "@ai-character-chat/api-types";

import { isCreatorPayoutCursorInvalidError } from "./creatorPayoutError";

type CreatorPayoutStatementsResponse = components["schemas"]["CreatorPayoutStatementsResponse"];

/** 다음 페이지 cursor. 서버의 `null`(마지막 페이지)은 `undefined` 로 바꾼다 — 무한 쿼리는 `undefined` 일 때만 "다음
 * 페이지 없음"으로 보고, `null` 을 그대로 넘기면 `hasNextPage` 가 참으로 남아 "더 보기"가 사라지지 않는다. */
export function toNextStatementsCursor(page: CreatorPayoutStatementsResponse): string | undefined {
  return page.nextCursor ?? undefined;
}

/** "더 보기"가 실패했을 때 할 일. cursor 를 서버가 읽지 못했으면(`restart`) 같은 cursor 로 다시 물어도 같으므로 내역을
 * 처음부터 다시 읽고, 그 밖의 실패(`keep`)는 불러온 내역을 그대로 두고 다시 시도할 수 있게 한다. */
export function toStatementsLoadMoreRecovery(error: unknown): "restart" | "keep" {
  return isCreatorPayoutCursorInvalidError(error) ? "restart" : "keep";
}
