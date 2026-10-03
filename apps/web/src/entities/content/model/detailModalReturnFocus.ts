type Focusable = { isConnected: boolean };

/**
 * 상세 모달이 닫힌 뒤 포커스를 돌려줄 곳. 탐색으로 닫혔으면(작가·해시태그·플레이 등 다른 화면으로 가는 길)
 * 돌려주지 않는다 — 옛 카드로 튀었다가 새 화면이 그 카드를 지우면 다시 `<body>` 로 떨어지고, 필터를 바꾼 뒤의
 * 착지점과도 싸운다. 그냥 닫혔으면 모달을 연 요소로, 그 요소가 사라졌으면 호출부가 준 대체 착지점으로 보낸다.
 * 둘 다 없으면 아무 데도 안 보낸다(라이브러리 기본 동작에 맡긴다).
 */
export function pickDetailModalReturnFocus<T extends Focusable>({
  isPlainClose,
  opener,
  fallback,
}: {
  isPlainClose: boolean;
  opener: T | null;
  fallback: T | null;
}): T | null {
  if (!isPlainClose) return null;
  if (opener?.isConnected) return opener;
  if (fallback?.isConnected) return fallback;
  return null;
}
