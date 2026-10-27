/** 소설 출처 목록의 방 하나가 보일 것. */
export type NovelSourceRowAction = { kind: "blocked" } | { kind: "open"; novelId: string } | { kind: "create" };

/**
 * 방마다 막힘 · 소설 열기 · 소설 만들기 중 하나. 막힘이 소설 열기보다 먼저다 — 원작이 소설 만들기를 막기 전에 만들어 둔
 * 빈 소설(첫 화가 없는 소설)이 있는 방도 서버는 막힌 방으로 보고, 그 소설은 열어도 화를 만들 수 없다. 채팅 방 더보기의
 * 「소설로 보기」도 같은 방을 막힌 항목으로 그린다.
 */
export function toNovelSourceRowAction(room: { novelId: string | null; novelCreationBlocked: boolean }): NovelSourceRowAction {
  if (room.novelCreationBlocked) return { kind: "blocked" };
  if (room.novelId !== null) return { kind: "open", novelId: room.novelId };
  return { kind: "create" };
}
