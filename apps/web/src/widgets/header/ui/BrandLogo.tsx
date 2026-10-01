type BrandLogoProps = {
  className?: string;
};

/**
 * 말풍선 ㄸ 심볼과 "또나" 글자를 한 장으로 묶은 워드마크.
 * 심볼 도형은 파비콘(`apps/web/brand/favicon.svg`)과 같으니 한쪽을 바꾸면 다른 쪽도 바꾼다.
 * 글자는 Pretendard Bold 윤곽을 path로 굳힌 것이고, 높이는 ㄸ 윗변부터 말풍선 꼬리 끝까지에 맞췄다.
 * 색은 `currentColor`라 링크 글자색을 따른다 — 헤더 로고는 강조 지점이 아니어서 무채색이다.
 * viewBox는 잉크 bbox에 맞춰 잘랐다.
 */
export function BrandLogo({ className }: BrandLogoProps) {
  return (
    <svg viewBox="16 24 274 84" className={className} aria-hidden>
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
      <path fill="currentColor" d="M203.2 69.2H172.8V31H202.5V40.4H184.6V60H203.2ZM208.6 97.9H132V88.5H164.2V72.9H175.8V88.5H208.6ZM167.6 40.4H149.7V59.7Q154.7 59.6 159.2 59.2Q163.6 58.7 168.1 57.8L169 67.4Q163.8 68.5 158.8 68.9Q153.7 69.2 147 69.2H143.2H137.9V31H167.6Z" />
      <path fill="currentColor" d="M288.9 65.3H277.1V107.5H265.3V24H277.1V55.7H288.9ZM225.4 77.4Q243.2 77.1 259.7 73.8L260.9 83.5Q251.1 85.5 241.2 86.3Q231.3 87.1 221 87.1H213.7V32H225.4Z" />
    </svg>
  );
}
