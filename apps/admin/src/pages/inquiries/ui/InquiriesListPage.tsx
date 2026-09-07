import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { useNavigate } from "@tanstack/react-router";

import {
  INQUIRY_CATEGORY_LABELS,
  INQUIRY_CATEGORY_OPTIONS,
  INQUIRY_STATUS_LABELS,
  isInquiryCategory,
  useInquiryListQuery,
  type InquiryCategory,
  type InquiryStatusFilter,
} from "@/entities/inquiry";
import { Pagination } from "@/shared/ui/Pagination";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";

const STATUS_FILTER_OPTIONS: { value: "all" | InquiryStatusFilter; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "pending", label: INQUIRY_STATUS_LABELS.pending },
  { value: "answered", label: INQUIRY_STATUS_LABELS.answered },
];

const CATEGORY_FILTER_OPTIONS: { value: "all" | InquiryCategory; label: string }[] = [
  { value: "all", label: "전체" },
  ...INQUIRY_CATEGORY_OPTIONS,
];

type InquiriesListPageProps = {
  page: number;
  status?: InquiryStatusFilter;
  category?: InquiryCategory;
  onPageChange: (page: number) => void;
  onStatusChange: (status?: InquiryStatusFilter) => void;
  onCategoryChange: (category?: InquiryCategory) => void;
}

export function InquiriesListPage({
  page,
  status,
  category,
  onPageChange,
  onStatusChange,
  onCategoryChange,
}: InquiriesListPageProps) {
  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-6 px-6 py-10">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">문의 관리</h1>

        <div className="flex gap-2">
          <Select
            value={category ?? "all"}
            onValueChange={(value) => onCategoryChange(isInquiryCategory(value) ? value : undefined)}
          >
            <SelectTrigger size="sm" aria-label="카테고리 필터" className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CATEGORY_FILTER_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            value={status ?? "all"}
            onValueChange={(value) => onStatusChange(isInquiryStatus(value) ? value : undefined)}
          >
            <SelectTrigger size="sm" aria-label="처리상태 필터" className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUS_FILTER_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <InquiriesTable page={page} status={status} category={category} onPageChange={onPageChange} />
    </main>
  );
}

type InquiriesTableProps = {
  page: number;
  status?: InquiryStatusFilter;
  category?: InquiryCategory;
  onPageChange: (page: number) => void;
};

/** 헤더(제목·필터)는 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다(`ReportsListPage` 관용구).
 * `AdminInquiryListItem`(BE 응답)에는 작성자 필드가 없다 — 목록에 "작성자" 열을 두지 않는다.
 * 작성자 정보는 상세(`AdminInquiryDetailResponse`)에만 있다. */
function InquiriesTable({ page, status, category, onPageChange }: InquiriesTableProps) {
  const inquiryListQuery = useInquiryListQuery({ page, status, category });
  const navigate = useNavigate();

  if (inquiryListQuery.isPending) {
    return <div className="h-64 animate-pulse rounded-xl bg-muted" />;
  }

  if (inquiryListQuery.isError) {
    return <p className="text-sm text-destructive-text">문의 목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  }

  if (inquiryListQuery.data.items.length === 0) {
    return <p className="text-sm text-muted-foreground">접수된 문의가 없어요.</p>;
  }

  return (
    <>
      <div className="overflow-hidden rounded-xl border border-border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>카테고리</TableHead>
              <TableHead>제목</TableHead>
              <TableHead>접수일</TableHead>
              <TableHead>상태</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {inquiryListQuery.data.items.map((item) => (
              <TableRow
                key={item.id}
                tabIndex={0}
                role="button"
                className="cursor-pointer"
                onClick={() => void navigate({ to: "/inquiries/$inquiryId", params: { inquiryId: item.id } })}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    void navigate({ to: "/inquiries/$inquiryId", params: { inquiryId: item.id } });
                  }
                }}
              >
                <TableCell>{INQUIRY_CATEGORY_LABELS[item.category]}</TableCell>
                <TableCell>{item.title}</TableCell>
                <TableCell>{formatDateTime(item.createdAt)}</TableCell>
                <TableCell>{INQUIRY_STATUS_LABELS[item.status]}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Pagination
        page={inquiryListQuery.data.page}
        totalPages={inquiryListQuery.data.totalPages}
        totalCount={inquiryListQuery.data.totalCount}
        onPageChange={onPageChange}
      />
    </>
  );
}

/** `SelectItem`의 value가 `string`이라 좁힘이 필요하다. `as` 대신 술어를 쓴다(TS-03, `ReportsListPage`의
 * `isReportStatus` 동형). 카테고리 쪽은 `isInquiryCategory`(entities)를 그대로 재사용한다 — `"all"`은
 * 애초에 유효한 카테고리가 아니라 자연히 걸러진다. */
function isInquiryStatus(value: string): value is InquiryStatusFilter {
  return STATUS_FILTER_OPTIONS.some((option) => option.value !== "all" && option.value === value);
}
