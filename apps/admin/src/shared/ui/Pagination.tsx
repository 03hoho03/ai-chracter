import { Button } from "@ai-character-chat/ui/components/button";

type PaginationProps = {
  page: number;
  totalPages: number;
  totalCount: number;
  onPageChange: (page: number) => void;
};

/** 목록 화면들이 함께 쓰는 이전/다음 페이지네이션. 320px 에서는 버튼 둘과 글자가 한 줄(288px)에 안 들어가
 * 넘치므로 줄바꿈을 허용한다 — 넓은 화면에서는 한 줄 그대로다. */
export function Pagination({ page, totalPages, totalCount, onPageChange }: PaginationProps) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-2">
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
