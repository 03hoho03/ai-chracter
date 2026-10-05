/** 위로 불러오기를 누르기 직전의 "바닥에서 본 스크롤 위치"를 담는 ref. */
type FromBottomRef = { current: number | undefined };
type ScrollBox = { scrollHeight: number; scrollTop: number };

/**
 * 앞 페이지를 받는 동안 스크롤 위치를 들고 있다가, 앞에 붙은 캐시가 그려질 때 `restorePrependScroll` 이 쓰고 지우게 둔다.
 * 받기가 끝난 순간에 지우면 안 된다 — TanStack Query 는 캐시 변경 알림을 setTimeout(0) 뒤로 미뤄, 받기가 풀린 뒤에야
 * 앞붙인 캐시가 그려진다. 여기서 지우는 건 그릴 일이 없을 때뿐이다: 실패했을 때, 그리고 받은 페이지가 앞에 붙지 않았을
 * 때(빈 페이지·이미 있는 메시지뿐·그사이 재조회로 첫 메시지가 바뀌어 버린 페이지). 남겨 두면 나중에 무관한 이유로 첫
 * 메시지가 바뀔 때 엉뚱한 위치로 튄다.
 */
export async function loadOlderKeepingScroll(
  fromBottomRef: FromBottomRef,
  scrollArea: ScrollBox,
  load: () => Promise<{ messages: readonly { id: string }[] }>,
  readFirstMessageId: () => string | undefined,
): Promise<void> {
  fromBottomRef.current = scrollArea.scrollHeight - scrollArea.scrollTop;
  let page: { messages: readonly { id: string }[] };
  try {
    page = await load();
  } catch (error) {
    fromBottomRef.current = undefined;
    throw error;
  }
  // 앞에 붙었다면 지금 첫 메시지는 받은 페이지에서 왔다.
  const firstMessageId = readFirstMessageId();
  if (!page.messages.some((message) => message.id === firstMessageId)) fromBottomRef.current = undefined;
}

/** 첫 메시지가 바뀐 렌더의 레이아웃 이펙트에서 부른다 — 앞에 붙은 높이만큼 스크롤을 밀어 읽던 메시지를 제자리에 두고 위치를 지운다. */
export function restorePrependScroll(fromBottomRef: FromBottomRef, scrollArea: ScrollBox) {
  const fromBottom = fromBottomRef.current;
  if (fromBottom === undefined) return;
  fromBottomRef.current = undefined;
  scrollArea.scrollTop = scrollArea.scrollHeight - fromBottom;
}
