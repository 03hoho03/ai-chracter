import { cn } from "@ai-character-chat/ui/lib/utils";
import type { ReactNode } from "react";

type DenseTableProps = {
  /** 표가 놓인 표면. 고정한 첫 열은 그 표면과 같은 불투명 채움이어야 아래로 밀려 지나가는 칸이 비치지 않는다. */
  surface: "background" | "card";
  /** 공용 `Table`(래퍼가 이미 가로 스크롤한다). */
  children: ReactNode;
};

/**
 * 카드 행으로 바꾸지 않는 밀집 분석 표(열이 많고 숫자를 가로로 비교하는 표)의 래퍼. 좁으면 표만 가로로 스크롤하고
 * 첫 열(행 이름)은 왼쪽에 고정해 어느 행을 읽는지 잃지 않게 한다. 경계는 그림자가 아니라 `border-r` 이다(정지 상태에
 * 그림자를 쓰지 않는다).
 *
 * 고정한 첫 열은 줄바꿈을 허용하고 하한(8rem)만 둔다 — 행 이름이 사용자가 쓴 글(작품명 등)이면 한 줄로 두었을 때 고정
 * 열이 화면을 다 차지해 나머지 칸을 스크롤해도 볼 수 없다. 상한은 없다(자동 표 레이아웃에서 칸의 `max-width` 는
 * 무시된다). 표가 넘쳐 스크롤될 때는 첫 열이 하한까지 줄어 여러 줄로 꺾이고, 자리가 남을 때만 그보다 넓어진다. 하한은
 * 다른 칸의 긴 글이 첫 열을 한 글자 폭으로 깎지 않게 한다.
 *
 * 카드 위에서는 `TableRow` 기본 hover(`bg-muted/50`)가 카드와 같은 값이라 보이지 않아 `secondary` 로 덮는다.
 */
export function DenseTable({ surface, children }: DenseTableProps) {
  return (
    <div
      className={cn(
        "[&_td:first-child]:min-w-32 [&_td:first-child]:whitespace-normal [&_td:first-child]:break-keep [&_td:first-child]:wrap-anywhere",
        "[&_td:first-child]:sticky [&_td:first-child]:left-0 [&_td:first-child]:z-10 [&_td:first-child]:border-r [&_td:first-child]:border-border [&_th:first-child]:sticky [&_th:first-child]:left-0 [&_th:first-child]:z-10 [&_th:first-child]:border-r [&_th:first-child]:border-border",
        // 고정 열은 불투명 채움이라 행 hover·선택 채움이 그 칸만 비켜 간다 — 행 머리 칸(`th scope="row"`)까지 같은 채움을
        // 따라가게 한다. 고른 행(`data-state="selected"`)도 같다.
        surface === "background"
          ? "[&_td:first-child]:bg-background [&_th:first-child]:bg-background [&_tr:hover_td:first-child]:bg-muted [&_tbody_tr:hover_th:first-child]:bg-muted [&_tr[data-state=selected]_:is(td,th):first-child]:bg-muted"
          : "[&_td:first-child]:bg-card [&_th:first-child]:bg-card [&_tbody_tr]:hover:bg-secondary/50 [&_tr:hover_td:first-child]:bg-secondary [&_tbody_tr:hover_th:first-child]:bg-secondary [&_tbody_tr[data-state=selected]]:bg-secondary [&_tr[data-state=selected]_:is(td,th):first-child]:bg-secondary",
      )}
    >
      {children}
    </div>
  );
}
