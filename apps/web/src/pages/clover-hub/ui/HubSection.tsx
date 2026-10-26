import type { ReactNode, Ref } from "react";

/** 섹션 안 텍스트 링크. `pages/mypage/ui/MyPagePage.tsx`의 "만든 작품과 초안 보기" 링크와 같은 관용구다. */
export const SECTION_LINK_CLASS =
  "w-fit text-sm font-medium whitespace-nowrap text-primary hover:underline focus-visible:underline";

/** 문장 속 링크. 문장 안에서 두 줄로 갈리지 않게 줄바꿈을 막는다. */
export const INLINE_LINK_CLASS =
  "whitespace-nowrap font-medium text-primary underline-offset-4 hover:underline focus-visible:underline";

/** 이 화면의 섹션 — 제목(Title 단, `text-xl`/600)과 내용. 상자로 감싸지 않는다: 감싸면 안의 `bg-muted` 스켈레톤이 카드
 * 표면 위에서 사라지고, 상품 행 카드가 카드 안 카드가 된다. */
export function HubSection({
  title,
  headingRef,
  children,
}: {
  title: string;
  /** 주면 제목이 프로그램 포커스를 받을 수 있다(`tabIndex={-1}`). */
  headingRef?: Ref<HTMLHeadingElement>;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-4">
      <h2
        ref={headingRef}
        tabIndex={headingRef ? -1 : undefined}
        className="text-xl font-semibold tracking-tight text-foreground outline-none"
      >
        {title}
      </h2>
      {children}
    </section>
  );
}
