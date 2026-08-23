import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { MoreHorizontal } from "lucide-react";
import type { ReactNode } from "react";

type ContentCardActionMenuProps = {
  /** 접근가능 이름에 넣을 작품 이름. 그리드에 같은 "⋯"가 수십 개 놓이므로 이름이 없으면 스크린리더
   * 버튼 목록에서 어느 작품의 메뉴인지 고를 수 없다. `ContentCard`가 `aria-labelledby`로 자기 이름을
   * 계산해서 이 라벨을 흡수하지 않는다(같은 파일의 그 주석 참고). */
  title: string;
  children: ReactNode;
};

/** `ContentCard`의 `actions` 슬롯 전용 "⋯" 메뉴 셸. 항목만 `children`으로 받는다.
 *
 * 셸을 여기 둔 이유는 이게 도메인 중립적인 아이콘 메뉴가 아니라 **`ContentCard`의 `actions` 계약**이기
 * 때문이다. 카드가 클릭 영역이라 넣는 쪽이 click·keydown을 모두 끊어야 하는데, 그 의무를 호출부에
 * 떠넘겼더니 실제로 두 호출부(`/my`·프로필)의 `aria-label`이 한 번 갈렸다. 셸이 소유하면 계약이 아니라
 * 구현이 된다.
 *
 * 이 셸이 소유하는 것은 **넷**이고 전부 `apps/web/CLAUDE.md`에 실측치와 함께 근거가 있다.
 * - **click·keydown 양쪽 stopPropagation**: 메뉴 콘텐츠는 body로 포털되지만 React 합성 이벤트는 컴포넌트
 *   트리를 타고 올라온다. 항목을 **키보드로** 고를 때의 Enter는 click이 아니라 keydown으로 카드에 닿아,
 *   막지 않으면 확인 모달과 카드의 상세 모달이 함께 열린다.
 * - **`hover:bg-secondary aria-expanded:bg-secondary`**: 포인터가 이 버튼 위에 있으면 카드도 동시에
 *   hover라 카드가 `bg-muted`가 되는데 `ghost`의 hover도 `bg-muted`라 정확히 1.0000:1로 사라진다.
 *   `secondary`는 카드의 두 표면(`background`/`muted`) 양쪽에서 살아남는다(실측 다크 1.1439 / 라이트 1.1239).
 * - **`w-auto`**: `DropdownMenuContent`의 폭이 트리거 폭(28px → `min-w-32`)에 고정돼 있어 조금만 긴
 *   라벨이 두 줄로 깨진다. 프리미티브를 고치면 헤더·알림 메뉴 폭이 함께 바뀌므로 call-site 처방이다.
 * - **`collisionPadding`**: Radix 기본값이 0이라, 좌측 열 카드의 `align="end"` 메뉴가 뷰포트를 넘칠 때
 *   충돌 보정이 딱 `x=0`에 붙여 놓는다(320px 실측 — 여백 0px). 카드 그리드는 뷰포트 가장자리까지 가는
 *   유일한 메뉴 트리거라 이 셸에서만 필요하다.
 * - **이름 있는 `aria-label`**(`title` prop) — 호출부 책임이 아니다. 근거는 그 prop의 주석에 있다. */
export function ContentCardActionMenu({ title, children }: ContentCardActionMenuProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={`${title} 더보기`}
          className="hover:bg-secondary aria-expanded:bg-secondary"
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
        >
          <MoreHorizontal aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        collisionPadding={8}
        className="w-auto"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => event.stopPropagation()}
      >
        {children}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
