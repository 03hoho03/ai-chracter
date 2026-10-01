import { cn } from "@ai-character-chat/ui/lib/utils";

type CloverIconProps = {
  className?: string;
};

const LEAF_PATH =
  "M0 0C-1.3-1-4.1-3-4.1-5.9A2.2 2.2 0 0 1 0-7A2.2 2.2 0 0 1 4.1-5.9C4.1-3 1.3-1 0 0Z";
const LEAF_ANGLES = [-45, 45, 135, -135];

/**
 * 재화 클로버의 아이콘. 하트 잎 네 장이 틈을 두고 모이고, 그 틈을 따라 진한 별이 뻗으며,
 * 줄기는 아래쪽 두 잎 사이에서 나와 오른쪽 아래로 휜다.
 *
 * 색을 `currentColor`로 두지 않고 초록으로 고정한다 — 클로버는 재화의 얼굴이라 어느 화면에서든
 * 같은 모양·같은 색으로 알아봐야 한다. 그래서 테마 토큰이 아니라 그림 자산으로 다룬다(값은
 * 다크·라이트 배경 양쪽에서 렌더링해 골랐다). 부족 같은 상태는 아이콘이 아니라 곁의 숫자가 말한다.
 */
export function CloverIcon({ className }: CloverIconProps) {
  return (
    <svg viewBox="0 0 24 24" className={cn("size-3.5", className)} aria-hidden>
      <path
        d="M12 13C12.2 17.2 14.6 19.8 19.2 20.6"
        fill="none"
        stroke="#3E9A50"
        strokeWidth={1.8}
        strokeLinecap="round"
      />
      <path
        d="M12 5.6Q12.5 10 16.4 10.5Q12.5 11 12 15.4Q11.5 11 7.6 10.5Q11.5 10 12 5.6Z"
        fill="#1F6A3B"
      />
      <g fill="#4EA75C" transform="translate(12 10.5)">
        {LEAF_ANGLES.map((angle) => (
          <path key={angle} d={LEAF_PATH} transform={`rotate(${angle}) translate(0 -1.15)`} />
        ))}
      </g>
    </svg>
  );
}
