import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Check } from "lucide-react";
import type { ReactNode } from "react";

export type DataListColumn<Row> = {
  id: string;
  header: string;
  cell: (row: Row) => ReactNode;
  align?: "start" | "end";
  /** 행 링크를 품는 열 — 정확히 하나. 이 셀 내용이 링크 글자(= 접근 이름)가 된다. */
  isPrimary?: true;
};

export type RowTargetProps = { className: string; children: ReactNode };

type DataListProps<Row> = {
  /** 표의 `<caption>`(화면에는 숨긴다). */
  caption: string;
  rows: readonly Row[];
  getRowKey: (row: Row) => string;
  columns: readonly DataListColumn<Row>[];
  /**
   * 행 전체를 덮는 대상. 보통 상세로 가는 타입 안전한 `Link` 이고, 상세 라우트가 없는 목록은 그 자리에 선택 버튼을
   * 그린다. 받은 props 를 그대로 넘긴다.
   */
  renderRowTarget: (row: Row, props: RowTargetProps) => ReactNode;
  /**
   * 한 행을 골라 같은 화면에서 펼치는 목록(상세 라우트 없음)이면 고른 행을 알려 준다. 고른 행은 `secondary` 채움에
   * 체크 글리프를 더한다 — 채움만으로는 배경 대비 3:1 에 못 미쳐 단서가 하나 더 필요하다(DESIGN.md Colors 절).
   */
  isRowSelected?: (row: Row) => boolean;
  card: {
    /** 카드 행의 대상 글자(= 접근 이름). 보통 대상 이름. */
    title: (row: Row) => ReactNode;
    /** 제목 아래 한 줄("스토리 · 공개 · 이용제한"). */
    meta: (row: Row) => ReactNode;
    /** 오른쪽 아래 끝(날짜 등). */
    trailing?: (row: Row) => ReactNode;
  };
};

/**
 * 링크 하나가 `::after` 로 행 전체를 덮는다 — 가운데 클릭·길게 누르기·새 탭이 네이티브 링크 그대로 되고, 다른 칸
 * 글자는 링크 밖이라 접근 이름에 섞이지 않는다. 포커스 링은 그 덮개에 그려 행 전체가 포커스로 보인다.
 * 대가로 행 위 글자를 드래그해 고르기가 링크 끌기가 된다 — 복사는 상세에서 한다.
 */
const ROW_TARGET_CLASS =
  "outline-none after:absolute after:inset-0 focus-visible:after:rounded-lg focus-visible:after:outline-1 focus-visible:after:-outline-offset-1 focus-visible:after:outline-ring focus-visible:after:ring-3 focus-visible:after:ring-ring/50";

/** 고른 행은 hover 에서도 채움을 유지한다(hover 채움과 같은 값이 되어 선택이 지워지지 않게). */
const SELECTED_ROW_CLASS = "data-[state=selected]:bg-secondary data-[state=selected]:hover:bg-secondary";

/**
 * 반응형 목록. 자기 폭(컨테이너 쿼리 `@2xl`, 672px) 이상이면 표, 미만이면 카드 행이다. 사이드바가 접히고 펴지면 같은
 * 뷰포트에서도 본문 폭이 바뀌어 뷰포트가 아니라 자기 폭으로 가른다.
 *
 * 두 모양이 DOM 에 함께 있고 한쪽은 `display:none` 이라 접근성 트리·Tab 순서에는 하나만 있다. 공용 `TableCell` 은
 * 줄바꿈하지 않는데, 행 대상 칸(이름·제목)만은 줄바꿈하게 둔다 — 사용자가 쓴 제목은 띄어쓰기가 있어도 100자쯤
 * 되면 표를 넓혀 상태·날짜 칸을 화면 밖으로 밀고, macOS 처럼 스크롤바가 숨는 환경에서는 그 칸이 있다는 단서도 없다.
 * 날짜·숫자 칸은 그대로 한 줄이다.
 */
export function DataList<Row>({ caption, rows, getRowKey, columns, renderRowTarget, isRowSelected, card }: DataListProps<Row>) {
  const hasSelection = isRowSelected !== undefined;
  /** 고를 수 있는 목록이면 대상 글자 앞에 체크 자리를 둔다 — 고르지 않은 행은 자리만 비워 글자 왼쪽 끝이 맞는다. */
  const withCheck = (row: Row, children: ReactNode) =>
    hasSelection ? (
      <span className="inline-flex min-w-0 items-start gap-1.5">
        <Check aria-hidden className={cn("mt-0.5 size-4 shrink-0 text-foreground", !isRowSelected(row) && "invisible")} />
        <span className="min-w-0">{children}</span>
      </span>
    ) : (
      children
    );

  return (
    <div className="@container">
      <div className="hidden overflow-hidden rounded-xl border border-border @2xl:block">
        <Table>
          <caption className="sr-only">{caption}</caption>
          <TableHeader>
            <TableRow>
              {columns.map((column) => (
                <TableHead key={column.id} className={cn(column.align === "end" && "text-right")}>
                  {/* 값 칸의 체크 자리(size-4 + gap-1.5)만큼 비워 제목과 값의 왼쪽 끝을 맞춘다. */}
                  {hasSelection && column.isPrimary ? (
                    <span className="inline-flex items-center gap-1.5">
                      <span aria-hidden className="size-4" />
                      {column.header}
                    </span>
                  ) : (
                    column.header
                  )}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              // 행 전체가 링크의 히트 영역이라 손가락 포인터에서 행 높이를 40px 로 올린다(칸 패딩만으로는 39px 남짓).
              <TableRow
                key={getRowKey(row)}
                data-state={isRowSelected?.(row) ? "selected" : undefined}
                className={cn("relative pointer-coarse:h-10", SELECTED_ROW_CLASS)}
              >
                {columns.map((column) => (
                  <TableCell
                    key={column.id}
                    className={cn(
                      column.align === "end" && "text-right tabular-nums",
                      // 최소 폭을 두어 다른 칸이 많아도 이름이 한두 글자 폭으로 깎이지 않게 한다.
                      column.isPrimary && "min-w-48 whitespace-normal break-keep wrap-anywhere",
                    )}
                  >
                    {column.isPrimary
                      ? renderRowTarget(row, { className: ROW_TARGET_CLASS, children: withCheck(row, column.cell(row)) })
                      : column.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ul aria-label={caption} className="divide-y divide-border overflow-hidden rounded-xl border border-border @2xl:hidden">
        {rows.map((row) => (
          <li
            key={getRowKey(row)}
            data-state={isRowSelected?.(row) ? "selected" : undefined}
            className={cn("relative flex flex-col gap-1 px-4 py-3 motion-safe:transition-colors hover:bg-muted/50", SELECTED_ROW_CLASS)}
          >
            {renderRowTarget(row, {
              className: cn(ROW_TARGET_CLASS, "text-left text-sm font-semibold text-foreground break-keep wrap-anywhere"),
              children: withCheck(row, card.title(row)),
            })}
            <div className="flex flex-wrap items-end justify-between gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <div className="flex min-w-0 flex-wrap items-center gap-x-1.5">{card.meta(row)}</div>
              {!!card.trailing && <div className="tabular-nums">{card.trailing(row)}</div>}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
