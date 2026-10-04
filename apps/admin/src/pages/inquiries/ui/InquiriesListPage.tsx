import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";

import {
  INQUIRY_CATEGORY_LABELS,
  INQUIRY_CATEGORY_OPTIONS,
  INQUIRY_STATUS_LABELS,
  INQUIRY_STATUS_OPTIONS,
  useInquiryListQuery,
  type AdminInquiryListResponse,
  type InquiryCategory,
  type InquiryStatusFilter,
} from "@/entities/inquiry";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { DataList, type DataListColumn } from "@/shared/ui/DataList";
import { FilterBar, selectFilter } from "@/shared/ui/FilterBar";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { Pagination } from "@/shared/ui/Pagination";
import { QueryState } from "@/shared/ui/QueryState";

type InquiriesListPageProps = {
  page: number;
  status?: InquiryStatusFilter;
  category?: InquiryCategory;
  onPageChange: (page: number) => void;
  onFilterChange: (patch: InquiryFilterPatch) => void;
}

type InquiryFilterPatch = {
  status?: InquiryStatusFilter;
  category?: InquiryCategory;
};

/** 두 필터 모두 entities가 Record 키에서 도출한 옵션을 그대로 쓴다 — 멤버를 여기 손으로 나열하면 서버에 값이
 * 늘어도 이 필터만 조용히 빠진다. */
export function InquiriesListPage({
  page,
  status,
  category,
  onPageChange,
  onFilterChange,
}: InquiriesListPageProps) {
  const resetFilters = () => onFilterChange({ category: undefined, status: undefined });

  return (
    <PageContainer>
      <PageHeader title="문의 관리" />

      <FilterBar
        fields={[
          selectFilter({
            id: "category",
            label: "카테고리",
            options: INQUIRY_CATEGORY_OPTIONS,
            value: category,
            defaultLabel: "전체",
            onChange: (value) => onFilterChange({ category: value }),
          }),
          selectFilter({
            id: "status",
            label: "처리상태",
            options: INQUIRY_STATUS_OPTIONS,
            value: status,
            defaultLabel: "전체",
            onChange: (value) => onFilterChange({ status: value }),
          }),
        ]}
        onReset={resetFilters}
      />

      <InquiriesList
        page={page}
        status={status}
        category={category}
        onPageChange={onPageChange}
        onReset={resetFilters}
      />
    </PageContainer>
  );
}

type InquiryListItem = AdminInquiryListResponse["items"][number];

const COLUMNS: readonly DataListColumn<InquiryListItem>[] = [
  { id: "category", header: "카테고리", cell: (item) => INQUIRY_CATEGORY_LABELS[item.category] },
  { id: "title", header: "제목", isPrimary: true, cell: (item) => item.title },
  { id: "created", header: "접수일", cell: (item) => formatDateTime(item.createdAt) },
  { id: "status", header: "상태", cell: (item) => INQUIRY_STATUS_LABELS[item.status] },
];

type InquiriesListProps = {
  page: number;
  status?: InquiryStatusFilter;
  category?: InquiryCategory;
  onPageChange: (page: number) => void;
  onReset: () => void;
};

/** 헤더(제목·필터)는 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다.
 * `AdminInquiryListItem`(BE 응답)에는 작성자 필드가 없다 — 목록에 "작성자" 열을 두지 않는다.
 * 작성자 정보는 상세(`AdminInquiryDetailResponse`)에만 있다. */
function InquiriesList({ page, status, category, onPageChange, onReset }: InquiriesListProps) {
  const inquiryListQuery = useInquiryListQuery({ page, status, category });
  const hasCondition = status !== undefined || category !== undefined;

  return (
    <QueryState
      query={inquiryListQuery}
      errorMessage="문의 목록을 불러오지 못했어요."
      isEmpty={(data) => data.items.length === 0}
      empty={
        hasCondition
          ? {
              title: "조건에 맞는 문의가 없어요.",
              action: (
                <Button type="button" variant="outline" size="sm" onClick={onReset}>
                  필터 초기화
                </Button>
              ),
            }
          : { title: "들어온 문의가 없어요." }
      }
    >
      {(data) => (
        <>
          <DataList
            caption="문의 목록"
            rows={data.items}
            getRowKey={(item) => item.id}
            columns={COLUMNS}
            renderRowTarget={(item, props) => <Link to="/inquiries/$inquiryId" params={{ inquiryId: item.id }} {...props} />}
            card={{
              title: (item) => item.title,
              meta: (item) => (
                <>
                  <span>{INQUIRY_CATEGORY_LABELS[item.category]}</span>
                  <span aria-hidden>·</span>
                  <span className="font-medium text-foreground">{INQUIRY_STATUS_LABELS[item.status]}</span>
                </>
              ),
              trailing: (item) => formatDateTime(item.createdAt),
            }}
          />

          <Pagination
            page={data.page}
            totalPages={data.totalPages}
            totalCount={data.totalCount}
            onPageChange={onPageChange}
          />
        </>
      )}
    </QueryState>
  );
}
