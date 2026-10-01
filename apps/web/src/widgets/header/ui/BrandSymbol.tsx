type BrandSymbolProps = {
  className?: string;
};

/**
 * ㄸ 전체가 말풍선 하나이고 첫 ㄷ 아래에서 꼬리가 왼쪽 아래로 내려오는 또나 심볼.
 * 도형은 파비콘(`apps/web/brand/favicon.svg`)과 같으니 한쪽을 바꾸면 다른 쪽도 바꾼다.
 * 색은 `currentColor`라 워드마크 글자색을 그대로 따른다 — 헤더 로고는 강조 지점이 아니어서 무채색이다.
 * viewBox는 글리프 bbox에 맞춰 잘랐다(파비콘의 타일 여백이 없다).
 */
export function BrandSymbol({ className }: BrandSymbolProps) {
  return (
    <svg viewBox="16 24 90 84" className={className} aria-hidden>
      <g
        fill="none"
        stroke="currentColor"
        strokeWidth={12}
        strokeLinejoin="round"
      >
        <path d="M54 30H34A12 12 0 0 0 22 42V70A12 12 0 0 0 34 82H54" />
        <path d="M106 30H86A12 12 0 0 0 74 42V70A12 12 0 0 0 86 82H106" />
      </g>
      <path
        d="M28 84H46L20 106Z"
        fill="currentColor"
        stroke="currentColor"
        strokeWidth={3}
        strokeLinejoin="round"
      />
    </svg>
  );
}
