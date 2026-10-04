import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { cn } from "@ai-character-chat/ui/lib/utils";
import type { ReactNode } from "react";

export type DataListColumn<Row> = {
  id: string;
  header: string;
  cell: (row: Row) => ReactNode;
  align?: "start" | "end";
  /** 행 링크를 품는 열 — 정확히 하나. 이 셀 내용이 링크 글자(= 접근 이름)가 된다. */
  isPrimary?: true;
};

export type RowLinkProps = { className: string; children: ReactNode };

type DataListProps<Row> = {
  /** 표의 `<caption>`(화면에는 숨긴다). */
  caption: string;
  rows: readonly Row[];
  getRowKey: (row: Row) => string;
  columns: readonly DataListColumn<Row>[];
  /** 행 링크는 호출부가 타입 안전한 `Link` 로 그리고 받은 props 를 그대로 넘긴다. */
  renderRowLink: (row: Row, props: RowLinkProps) => ReactNode;
  card: {
    /** 카드 행의 링크 글자(= 접근 이름). 보통 대상 이름. */
    title: (row: Row) => string;
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
const ROW_LINK_CLASS =
  "outline-none after:absolute after:inset-0 focus-visible:after:rounded-lg focus-visible:after:outline-1 focus-visible:after:-outline-offset-1 focus-visible:after:outline-ring focus-visible:after:ring-3 focus-visible:after:ring-ring/50";

/**
 * 반응형 목록. 자기 폭(컨테이너 쿼리 `@2xl`, 672px) 이상이면 표, 미만이면 카드 행이다. 사이드바가 접히고 펴지면 같은
 * 뷰포트에서도 본문 폭이 바뀌어 뷰포트가 아니라 자기 폭으로 가른다.
 *
 * 두 모양이 DOM 에 함께 있고 한쪽은 `display:none` 이라 접근성 트리·Tab 순서에는 하나만 있다. 표 칸은
 * 줄바꿈하지 않아(공용 `TableCell`) 긴 이름이 표를 넓히지만, 좁은 폭에서는 카드 행이 이름을 줄바꿈한다.
 */
export function DataList<Row>({ caption, rows, getRowKey, columns, renderRowLink, card }: DataListProps<Row>) {
  return (
    <div className="@container">
      <div className="hidden overflow-hidden rounded-xl border border-border @2xl:block">
        <Table>
          <caption className="sr-only">{caption}</caption>
          <TableHeader>
            <TableRow>
              {columns.map((column) => (
                <TableHead key={column.id} className={cn(column.align === "end" && "text-right")}>
                  {column.header}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              // 행 전체가 링크의 히트 영역이라 손가락 포인터에서 행 높이를 40px 로 올린다(칸 패딩만으로는 39px 남짓).
              <TableRow key={getRowKey(row)} className="relative pointer-coarse:h-10">
                {columns.map((column) => (
                  <TableCell key={column.id} className={cn(column.align === "end" && "text-right tabular-nums")}>
                    {column.isPrimary ? renderRowLink(row, { className: ROW_LINK_CLASS, children: column.cell(row) }) : column.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ul aria-label={caption} className="divide-y divide-border overflow-hidden rounded-xl border border-border @2xl:hidden">
        {rows.map((row) => (
          <li key={getRowKey(row)} className="relative flex flex-col gap-1 px-4 py-3 motion-safe:transition-colors hover:bg-muted/50">
            {renderRowLink(row, {
              className: cn(ROW_LINK_CLASS, "text-sm font-semibold text-foreground break-keep wrap-anywhere"),
              children: card.title(row),
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
