/**
 * techspec-content-detail.md §1 — 모달 경로에서 렌더링되는 위젯은 매치된 라우트가 홈이라
 * TanStack Router의 `useSearch()`를 쓸 수 없다. 대신 `window.location.search`를 직접 읽어
 * 모달/풀페이지 양쪽에서 동일하게 동작하게 한다.
 */
export function useRawSearchParams(): URLSearchParams {
  return new URLSearchParams(window.location.search);
}
