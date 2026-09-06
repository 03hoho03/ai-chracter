import { Button } from "@ai-character-chat/ui/components/button";

type PaginationProps = {
  page: number;
  totalPages: number;
  totalCount: number;
  onPageChange: (page: number) => void;
};

/** ReportsListPage/AppealsListPage에 동형으로 중복됐던 이전/다음 페이지네이션 UI를 추출한 것.
 * 마크업·클래스는 원본 그대로 옮겼다 — 화면이 조금도 달라지면 안 된다. */
export function Pagination({ page, totalPages, totalCount, onPageChange }: PaginationProps) {
  return (
    <div className="flex items-center justify-center gap-3">
      <Button type="button" variant="outline" size="sm" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
        이전
      </Button>
      <span className="text-sm text-muted-foreground">
        {page} / {totalPages} 페이지 (총 {totalCount}건)
      </span>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={page >= totalPages}
        onClick={() => onPageChange(page + 1)}
      >
        다음
      </Button>
    </div>
  );
}
