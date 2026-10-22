/**
 * 화면 안에 들고 있는 읽은 자리. 서버에는 문단 번호만 가지만, 세션 안에서는 문단 안 글자 위치와 화 끝 화면 표시를
 * 함께 든다 — 긴 문단 하나가 통째로 덮은 화면이나 화 끝 화면에서 창 크기·글꼴·설정이 바뀌어 다시 흐를 때 문단
 * 번호만으로 돌아가면 그 문단이 시작하는 앞 화면으로 되돌아가기 때문이다. 같은 이유로 그 화면을 문단 글이 아니라 삽화가
 * 열면(글이 앞 화면에서 끝나고 뒤 그림만 남은 화면, 앞 그림이 둘 이상이라 문단 머리 뒤에 그림만 남은 화면) 그 그림을
 * 든다.
 */
export type PageAnchor = {
  paragraphIndex: number;
  /** 문단 안에서 그 화면의 첫 글자 위치. 문단이 그 화면에서 시작하면(또는 서버 값에서 열면) 0 이다. */
  charOffset: number;
  isAtEnd: boolean;
  /** 그 화면이 문단 머리가 아니라 문단 글 중간에서 시작하는가 — 그러면 글자 위치(0 이어도)가 든 화면으로 돌아간다.
   * 문단 앞 그림들 뒤에서 글이 새 화면으로 넘어가 시작하면 글자 위치가 0 인데도 머리 화면과 다르다. */
  isCovered?: boolean;
  /** 그 화면을 연 삽화 블록의 키. 있으면 그 그림이 든 화면으로 돌아간다. */
  illustrationKey?: string;
};

/**
 * 사용자가 옮겨 간 화면을 대표하는 문단. 그 화면에서 머리가 시작하는 첫 문단이고, 시작하는 문단이 없으면(긴 문단 하나가
 * 화면을 통째로 덮으면) 덮고 있는 문단이다. 화 끝 화면은 늘 새 화면에서 시작해 거기서 시작하는 문단이 없으므로 같은
 * 규칙으로 마지막 문단이 된다 — 거기까지 왔으면 본문을 다 지나왔다. 화면 하나를 고르는 규칙이 이것 하나라 저장하는
 * 문단과 되돌아갈 화면이 서로 어긋나지 않는다.
 *
 * `leadScreens[i]` 는 문단 i 의 머리가 시작하는 화면이고(`toLeadScreens`) 문단 순서대로 줄지 않는다. 문단이 하나
 * 이상일 때만 부른다.
 */
export function toAnchorParagraphIndex({
  leadScreens,
  screen,
}: {
  leadScreens: readonly number[];
  screen: number;
}): number {
  let covering = 0;
  for (const [index, start] of leadScreens.entries()) {
    if (start === screen) return index;
    if (start > screen) break;
    covering = index;
  }
  return covering;
}

/**
 * 다시 흐른 뒤 돌아갈 화면. 화 끝 화면에 있었으면 화 끝 화면, 앵커가 그림을 들었으면 그 그림이 든 화면, 아니면 앵커
 * 문단 안 글자 위치가 든 화면이다. `illustrationScreen`·`offsetScreen` 은 호출부가 잰 화면인데, 앵커가 그것을 들지
 * 않았거나 재지 못했으면(그림 목록이 바뀌어 그 그림이 없어졌으면) 비우고 문단 머리가 시작하는 화면을 쓴다. 문단
 * 번호가 본문보다 크면(저장 뒤 본문이 줄었으면) 마지막 문단으로 친다.
 */
export function toRestoreScreen({
  anchor,
  leadScreens,
  endScreen,
  offsetScreen,
  illustrationScreen,
}: {
  anchor: PageAnchor;
  leadScreens: readonly number[];
  endScreen: number;
  offsetScreen?: number;
  illustrationScreen?: number;
}): number {
  if (anchor.isAtEnd) return endScreen;
  const index = Math.min(anchor.paragraphIndex, leadScreens.length - 1);
  return Math.min(illustrationScreen ?? offsetScreen ?? leadScreens[index] ?? 0, endScreen);
}

/** 쪽 나누기에서 잰 삽화 블록 하나 — 어느 문단의 앞·뒤에 서는가와 그 블록이 든 화면. */
export type MeasuredIllustration = {
  key: string;
  paragraphIndex: number;
  placement: "before" | "after";
  screen: number;
};

/**
 * 문단마다 머리가 시작하는 화면. 문단의 머리는 그 문단 앞 그림들이고, 첫 문단의 머리는 화 머리라 늘 첫 화면이다.
 * 앞 그림이 없으면 문단 글이 시작하는 화면 그대로다 — 그래서 그림 없는 화에서는 `startScreens` 와 같다(첫 문단도
 * 화 머리 바로 뒤에 흘러 늘 첫 화면에서 시작한다).
 *
 * 머리로 재는 이유: 첫 쪽에 화 머리만 남고 문단 0 앞 그림이 다음 쪽으로 넘어간 화를 처음 열면, 글이 시작하는 화면으로
 * 되돌리면 화 제목이 있는 첫 쪽을 건너뛴다. 앞 그림만 있는 화면도 머리가 그 화면에서 시작하는 뒤 문단의 자리가 된다.
 * `illustrations` 는 문서 순서다.
 */
export function toLeadScreens({
  startScreens,
  illustrations,
}: {
  startScreens: readonly number[];
  illustrations: readonly Omit<MeasuredIllustration, "key">[];
}): number[] {
  return startScreens.map((start, index) => {
    if (index === 0) return 0;
    const lead = illustrations.find((block) => block.paragraphIndex === index && block.placement === "before");
    return lead?.screen ?? start;
  });
}

/**
 * 덮인 화면(그 화면에서 머리가 시작하는 문단이 없는 화면)을 무엇으로 들까. 덮는 문단의 앞 그림이 그 화면에 있으면 그
 * 그림(글보다 앞에 놓인다), 아니면 문단 글이 그 화면에 걸쳐 있으면 글자 위치, 아니면 그 화면의 뒤 그림이다 — 글이 앞
 * 화면에서 끝나 뒤 그림만 남은 화면에서 글자 위치를 들면 그 위치가 앞 화면에 있어 다시 잴 때 한 쪽 앞으로 튄다.
 * `illustrations` 는 덮는 문단의 그림들을 문서 순서로.
 */
export function toCoveredAnchorTarget({
  screen,
  textStartScreen,
  textEndScreen,
  illustrations,
}: {
  screen: number;
  textStartScreen: number;
  textEndScreen: number;
  illustrations: readonly Pick<MeasuredIllustration, "key" | "placement" | "screen">[];
}): { kind: "text" } | { kind: "illustration"; key: string } {
  const onScreen = (placement: "before" | "after") =>
    illustrations.find((block) => block.placement === placement && block.screen === screen);
  const before = onScreen("before");
  if (before !== undefined) return { kind: "illustration", key: before.key };
  if (textStartScreen <= screen && screen <= textEndScreen) return { kind: "text" };
  const after = onScreen("after");
  return after === undefined ? { kind: "text" } : { kind: "illustration", key: after.key };
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
