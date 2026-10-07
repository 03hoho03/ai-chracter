/** 지운 화들의 캐시를 지금 버려도 되는가. 화면이 아직 그 화들 중 하나를 그리고 있으면 안 된다 — 그 화의 본문·판
 * 쿼리에 관찰자가 남아 있어 지우는 순간 다시 받아 404 가 난다. 버릴 것이 없어도 거짓이다. */
export function canRemoveDeletedChapterCaches(
  deletedChapterIds: readonly string[],
  shownChapterId: string | undefined,
): boolean {
  if (deletedChapterIds.length === 0) return false;
  return shownChapterId === undefined || !deletedChapterIds.includes(shownChapterId);
}
