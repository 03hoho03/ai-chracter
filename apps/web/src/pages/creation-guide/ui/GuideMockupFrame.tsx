import { cn } from "@ai-character-chat/ui/lib/utils";

type GuideMockupFrameProps = {
  caption: string;
  /** 보이는 캡션 뒤에 화면 낭독기에만 읽히는 설명(배치표처럼 그림만으로 정보를 주는 목업). */
  srDescription?: string;
  className?: string;
  children: React.ReactNode;
};

/**
 * 빌더 칸 그림을 담는 액자. 캡션("예시 작품 입력 · …")이 figure 의 이름이 되어 낭독기에 "그림"으로 읽히고, 보이는
 * 글자로도 이것이 입력칸이 아니라 예시 작품이 채운 모습이라는 것을 말한다.
 *
 * 면이 `card` 가 아니라 `background` 인 이유: 빌더 칸이 앉는 면과 같아야 안의 토큰을 빌더에서 그대로 옮길 수 있다. `card`
 * 면이면 빌더의 `bg-muted` 웰(표지 자리 등)이 같은 값이라 사라지고, `bg-background` 카드 머리 줄이 바닥보다 어두워진다.
 */
export function GuideMockupFrame({ caption, srDescription, className, children }: GuideMockupFrameProps) {
  return (
    <figure
      className={cn(
        "m-0 flex min-w-0 cursor-default flex-col gap-3 rounded-xl border border-border bg-background p-3 sm:p-4",
        className,
      )}
    >
      <figcaption className="text-xs font-medium text-muted-foreground">
        {caption}
        {srDescription && <span className="sr-only"> {srDescription}</span>}
      </figcaption>
      {children}
    </figure>
  );
}
