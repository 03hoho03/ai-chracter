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
 * 카드 위에서는 `TableRow` 기본 hover(`bg-muted/50`)가 카드와 같은 값이라 보이지 않아 `secondary` 로 덮는다.
 */
export function DenseTable({ surface, children }: DenseTableProps) {
  return (
    <div
      className={cn(
        "[&_td:first-child]:sticky [&_td:first-child]:left-0 [&_td:first-child]:z-10 [&_td:first-child]:border-r [&_td:first-child]:border-border [&_th:first-child]:sticky [&_th:first-child]:left-0 [&_th:first-child]:z-10 [&_th:first-child]:border-r [&_th:first-child]:border-border",
        surface === "background"
          ? "[&_td:first-child]:bg-background [&_th:first-child]:bg-background [&_tr:hover_td:first-child]:bg-muted"
          : "[&_td:first-child]:bg-card [&_th:first-child]:bg-card [&_tbody_tr]:hover:bg-secondary/50 [&_tr:hover_td:first-child]:bg-secondary",
      )}
    >
      {children}
    </div>
  );
}
