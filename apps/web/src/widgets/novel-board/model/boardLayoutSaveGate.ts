/**
 * 카드 자리를 지금 저장해도 되는가. 저장은 서버의 배치를 통째로 바꾸므로, 화면이 서버 배치의 일부를 모르는 채
 * 저장하면 모르는 자리가 지워진다.
 *
 * - 배치를 받지 못했으면(오류) 화면은 자동 배치다 — 그대로 저장하면 사용자가 옮겨 둔 자리를 자동 배치로 덮는다.
 * - 인물 목록이 아직 없으면 화면에 인물 카드가 없다 — 그때 저장하면 인물 카드 자리(`character:*`)가 빠진다.
 */
export function canSaveBoardLayout({
  isLayoutFailed,
  hasCharacters,
}: {
  isLayoutFailed: boolean;
  hasCharacters: boolean;
}): boolean {
  return !isLayoutFailed && hasCharacters;
}
