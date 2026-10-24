import { z } from "zod";

import { statRewindSchema, type StatRewind } from "./chatStream";

const deleteMessageResponseSchema = z.object({ statRewind: statRewindSchema.nullable() });

/** 메시지 삭제 응답에서 서버가 지운 턴의 스탯을 어떻게 했는지 읽는다. 알릴 것이 없으면 undefined 다 — 서버가 null 을 준 경우,
 * 스탯을 되돌리기 전의 서버가 본문 없는 204 를 준 경우, 모르는 값이 온 경우 모두. 어느 쪽이든 삭제 자체는 성공이라 던지지 않는다. */
export function toDeletedMessageStatRewind(data: unknown): StatRewind | undefined {
  const parsed = deleteMessageResponseSchema.safeParse(data);
  return parsed.success ? (parsed.data.statRewind ?? undefined) : undefined;
}
