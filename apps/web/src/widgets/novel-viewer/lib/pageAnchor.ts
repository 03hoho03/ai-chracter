/**
 * 화면 안에 들고 있는 읽은 자리. 서버에는 문단 번호만 가지만, 세션 안에서는 문단 안 글자 위치와 화 끝 화면 표시를
 * 함께 든다 — 긴 문단 하나가 통째로 덮은 화면이나 화 끝 화면에서 창 크기·글꼴·설정이 바뀌어 다시 흐를 때 문단
 * 번호만으로 돌아가면 그 문단이 시작하는 앞 화면으로 되돌아가기 때문이다.
 */
export type PageAnchor = {
  paragraphIndex: number;
  /** 문단 안에서 그 화면의 첫 글자 위치. 문단이 그 화면에서 시작하면(또는 서버 값에서 열면) 0 이다. */
  charOffset: number;
  isAtEnd: boolean;
};

/**
 * 사용자가 옮겨 간 화면을 대표하는 문단. 그 화면에서 시작하는 첫 문단이고, 시작하는 문단이 없으면(긴 문단 하나가
 * 화면을 통째로 덮으면) 덮고 있는 문단이다. 화 끝 화면은 늘 새 화면에서 시작해 거기서 시작하는 문단이 없으므로 같은
 * 규칙으로 마지막 문단이 된다 — 거기까지 왔으면 본문을 다 지나왔다. 화면 하나를 고르는 규칙이 이것 하나라 저장하는
 * 문단과 되돌아갈 화면이 서로 어긋나지 않는다.
 *
 * `startScreens[i]` 는 문단 i 가 시작하는 화면이고 문단 순서대로 줄지 않는다. 문단이 하나 이상일 때만 부른다.
 */
export function toAnchorParagraphIndex({
  startScreens,
  screen,
}: {
  startScreens: readonly number[];
  screen: number;
}): number {
  let covering = 0;
  for (const [index, start] of startScreens.entries()) {
    if (start === screen) return index;
    if (start > screen) break;
    covering = index;
  }
  return covering;
}

/**
 * 다시 흐른 뒤 돌아갈 화면. 화 끝 화면에 있었으면 화 끝 화면, 아니면 앵커 문단 안 글자 위치가 든 화면이다.
 * `offsetScreen` 은 호출부가 글자 위치로 잰 화면인데, 글자 위치가 0 이거나 재지 못했으면 비우고 문단이 시작하는
 * 화면을 쓴다. 문단 번호가 본문보다 크면(저장 뒤 본문이 줄었으면) 마지막 문단으로 친다.
 */
export function toRestoreScreen({
  anchor,
  startScreens,
  endScreen,
  offsetScreen,
}: {
  anchor: PageAnchor;
  startScreens: readonly number[];
  endScreen: number;
  offsetScreen?: number;
}): number {
  if (anchor.isAtEnd) return endScreen;
  const index = Math.min(anchor.paragraphIndex, startScreens.length - 1);
  return Math.min(offsetScreen ?? startScreens[index] ?? 0, endScreen);
}

/** 다 읽음 — 마지막 문단이 시작하는 화면에 왔거나 지나왔다. 화 끝 화면으로 바로 건너뛰어도(End 키·슬라이더) 참이다.
 * 스크롤 모드가 마지막 문단이 화면에 들어오기만 하면 다 읽음으로 치는 것과 같은 뜻이다. */
export function isFinishedScreen({
  screen,
  lastParagraphScreen,
}: {
  screen: number;
  lastParagraphScreen: number;
}): boolean {
  return screen >= lastParagraphScreen;
}
