import { ChevronDown } from "lucide-react";

import { GUIDE_SUMMARY_CLASS } from "../config/guideStyles";

type GuideDisclosureProps = {
  summary: string;
  /**
   * 화면에는 안 보이고 접기 줄 이름 뒤에 괄호로 붙는 칸 이름. 한 페이지에 "자세히"가 여럿이라 접기 줄만 모아 훑는 낭독기
   * 탐색에서 어느 칸의 것인지 가려지게 한다. 뒤에 붙이는 이유: 보이는 글자가 이름 맨 앞에 그대로 남아야 보이는 라벨이
   * 접근 가능한 이름의 접두가 된다(WCAG 2.5.3 Label in Name 이 권하는 형태 — 개요의 칸 링크 이름도 같은 순서다).
   */
  context?: string;
  children: React.ReactNode;
};

/**
 * 칸 블록의 "자세히"·"나쁜 예" 접기. 네이티브 `<details>` 라 키보드·스크린리더·페이지 내 찾기가 따로 손대지 않아도
 * 동작하고, 펼침 상태는 저장하지 않는다(다시 들어오면 접혀 있다 — 페이지 길이를 접힌 상태로 맞췄다).
 *
 * 펼침은 즉시다. 접기 줄이 페이지에 여럿인 읽기 화면이라 펼칠 때마다 움직임을 주면 상태 전달보다 장식에 가깝다(빌더의
 * 접기 카드도 즉시다). 패널 간격을 `gap` 이 아니라 위 패딩으로 주는 이유: 패널은 `summary` 의 형제라 `details` 가 flex 가
 * 아니면 gap 을 받지 못하고, `details` 를 flex 로 바꾸는 동작은 브라우저마다 다르다.
 */
export function GuideDisclosure({ summary, context, children }: GuideDisclosureProps) {
  return (
    <details className="group">
      <summary className={GUIDE_SUMMARY_CLASS}>
        <ChevronDown aria-hidden className="size-4 shrink-0 text-muted-foreground group-open:rotate-180" />
        {summary}
        {context && <span className="sr-only">{` (${context})`}</span>}
      </summary>
      <div className="flex flex-col gap-3 pt-2 pb-1">{children}</div>
    </details>
  );
}
