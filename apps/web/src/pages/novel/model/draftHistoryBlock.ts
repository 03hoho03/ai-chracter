import type { ShouldBlockFn } from "@tanstack/react-router";

// 라우터가 기록 이동 종류(`PUSH`·`BACK` 등)의 타입을 따로 내보내지 않아 차단 함수의 인자에서 꺼낸다.
type HistoryAction = Parameters<ShouldBlockFn>[0]["action"];

/** 브라우저 뒤로가 고치던 글을 버리기 전에 확인을 받아야 하는가.
 *
 * 같은 소설 안에서 뒤로 가면 `?chapter=` 만 바뀌어 고치던 장이 새로 그려지고 쓰던 글이 사라진다. 화면이 스스로
 * 하는 이동(`PUSH`·`REPLACE` — 목차·새 장 링크·장 번호 박기)은 그 자리에서 이미 확인하거나 장이 바뀌지 않으므로
 * 여기서 다시 묻지 않는다. 앞으로·여러 칸 이동은 막지 않는다 — 라우터(`@tanstack/history`)가 막은 기록 이동을
 * 되돌릴 때 언제나 앞으로 한 칸(`history.go(1)`)을 가서, 뒤로가 아닌 이동을 막으면 주소와 화면이 어긋난다. 다른
 * 화면으로 가는 기록 이동은 이 확인의 대상이 아니다. */
export function shouldConfirmDraftDiscardOnHistory({
  action,
  currentPathname,
  nextPathname,
  isDraftDirty,
}: {
  action: HistoryAction;
  currentPathname: string;
  nextPathname: string;
  isDraftDirty: boolean;
}): boolean {
  if (!isDraftDirty) return false;
  if (action !== "BACK") return false;
  return currentPathname === nextPathname;
}
