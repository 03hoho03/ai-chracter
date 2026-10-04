import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";

import {
  CONTENT_TYPE_LABELS,
  CONTENT_TYPE_OPTIONS,
  CONTENT_VISIBILITY_LABELS,
  CONTENT_VISIBILITY_OPTIONS,
  MODERATION_STATUS_LABELS,
  MODERATION_STATUS_OPTIONS,
  useContentListQuery,
  type AdminContentListParams,
  type AdminContentListResponse,
  type ContentModerationStatusFilter,
  type ContentSortOption,
  type ContentTypeFilter,
  type ContentVisibilityFilter,
} from "@/entities/admin-content";
import { formatCount } from "@/shared/lib/format/formatCount";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { DataList, type DataListColumn } from "@/shared/ui/DataList";
import { FilterBar, selectFilter } from "@/shared/ui/FilterBar";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { Pagination } from "@/shared/ui/Pagination";
import { QueryState } from "@/shared/ui/QueryState";

import { HomeCurationStatus } from "./HomeCurationStatus";

/** 정렬만 도메인 라벨이 아니라 화면 전용 목록이라 여기 둔다(`CONTENT_SORT_OPTIONS`는 서버 스키마가 아니라 admin이
 * 정한 값이다). 필터 셋은 entities가 Record 키에서 도출한 옵션을 그대로 쓴다 — 멤버를 여기 손으로 나열하면 서버에
 * 값이 늘어도 이 필터만 조용히 빠진다. */
const SORT_OPTIONS: { value: ContentSortOption; label: string }[] = [
  { value: "recent", label: "최신순" },
  { value: "views", label: "조회수" },
  { value: "chats", label: "채팅수" },
];

type ContentFilterPatch = {
  type?: ContentTypeFilter;
  visibility?: ContentVisibilityFilter;
  moderationStatus?: ContentModerationStatusFilter;
  q?: string;
  sort?: ContentSortOption;
};

type ContentsListPageProps = {
  page: number;
  type?: ContentTypeFilter;
  visibility?: ContentVisibilityFilter;
  moderationStatus?: ContentModerationStatusFilter;
  q?: string;
  sort?: ContentSortOption;
  onPageChange: (page: number) => void;
  onFilterChange: (patch: ContentFilterPatch) => void;
};

/** 필터·검색·정렬·페이지는 전부 라우트 search에 담긴다(routes/contents.index.tsx).
 * 이름 검색은 제출 기반이다 — 타이핑마다 요청을 날리지 않는다. */
export function ContentsListPage({
  page,
  type,
  visibility,
  moderationStatus,
  q,
  sort,
  onPageChange,
  onFilterChange,
}: ContentsListPageProps) {
  const resetFilters = () => onFilterChange({ type: undefined, visibility: undefined, moderationStatus: undefined });
  const hasCondition = type !== undefined || visibility !== undefined || moderationStatus !== undefined || q !== undefined;

  return (
    <PageContainer>
      <PageHeader title="작품 관리" />

      <FilterBar
        search={{
          label: "작품 이름 검색",
          placeholder: "작품 이름 검색",
          value: q,
          onSubmit: (nextQuery) => onFilterChange({ q: nextQuery }),
        }}
        fields={[
          selectFilter({
            id: "type",
            label: "종류",
            options: CONTENT_TYPE_OPTIONS,
            value: type,
            defaultLabel: "전체",
            onChange: (value) => onFilterChange({ type: value }),
          }),
          selectFilter({
            id: "visibility",
            label: "공개범위",
            options: CONTENT_VISIBILITY_OPTIONS,
            value: visibility,
            defaultLabel: "전체",
            onChange: (value) => onFilterChange({ visibility: value }),
          }),
          selectFilter({
            id: "moderation-status",
            label: "상태",
            options: MODERATION_STATUS_OPTIONS,
            value: moderationStatus,
            defaultLabel: "전체",
            onChange: (value) => onFilterChange({ moderationStatus: value }),
          }),
          // 정렬에는 "전체"가 없다 — 비어 있으면 최신순으로 보이고, 최신순을 고르면 search 에 `recent` 가 실린다.
          selectFilter({
            id: "sort",
            label: "정렬",
            role: "sort",
            options: SORT_OPTIONS,
            value: sort ?? "recent",
            onChange: (value) => onFilterChange({ sort: value }),
          }),
        ]}
        onReset={resetFilters}
      />

      <HomeCurationStatus />

      <ContentsList
        params={{ page, type, visibility, moderationStatus, q, sort }}
        hasCondition={hasCondition}
        onReset={() => onFilterChange({ type: undefined, visibility: undefined, moderationStatus: undefined, q: undefined })}
        onPageChange={onPageChange}
      />
    </PageContainer>
  );
}

type ContentListItem = AdminContentListResponse["items"][number];

const COLUMNS: readonly DataListColumn<ContentListItem>[] = [
  { id: "name", header: "이름", isPrimary: true, cell: (item) => item.name || "(이름 없음)" },
  { id: "type", header: "종류", cell: (item) => <span className="text-muted-foreground">{CONTENT_TYPE_LABELS[item.type]}</span> },
  {
    id: "visibility",
    header: "공개범위",
    cell: (item) => <span className="text-muted-foreground">{CONTENT_VISIBILITY_LABELS[item.visibility]}</span>,
  },
  { id: "status", header: "상태", cell: (item) => MODERATION_STATUS_LABELS[item.moderationStatus] },
  { id: "views", header: "조회수", align: "end", cell: (item) => formatCount(item.viewCount) },
  { id: "chats", header: "채팅수", align: "end", cell: (item) => formatCount(item.chatCount) },
  { id: "created", header: "등록일시", cell: (item) => formatDateTime(item.createdAt) },
];

type ContentsListProps = {
  params: AdminContentListParams;
  /** 필터·검색어가 하나라도 걸렸는지 — 빈 결과의 안내가 갈린다. */
  hasCondition: boolean;
  onReset: () => void;
  onPageChange: (page: number) => void;
};

/** 머리(제목·필터)는 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function ContentsList({ params, hasCondition, onReset, onPageChange }: ContentsListProps) {
  const contentListQuery = useContentListQuery(params);

  return (
    <QueryState
      query={contentListQuery}
      errorMessage="작품 목록을 불러오지 못했어요."
      isEmpty={(data) => data.items.length === 0}
      empty={
        hasCondition
          ? {
              title: "조건에 맞는 작품이 없어요.",
              action: (
                <Button type="button" variant="outline" size="sm" onClick={onReset}>
                  검색·필터 초기화
                </Button>
              ),
            }
          : { title: "아직 등록된 작품이 없어요. 작가가 발행하면 여기에 나타나요." }
      }
    >
      {(data) => (
        <>
          <DataList
            caption="작품 목록"
            rows={data.items}
            getRowKey={(item) => item.id}
            columns={COLUMNS}
            renderRowTarget={(item, props) => <Link to="/contents/$contentId" params={{ contentId: item.id }} {...props} />}
            card={{
              title: (item) => item.name || "(이름 없음)",
              meta: (item) => (
                <>
                  <span>{CONTENT_TYPE_LABELS[item.type]}</span>
                  <span aria-hidden>·</span>
                  <span>{CONTENT_VISIBILITY_LABELS[item.visibility]}</span>
                  <span aria-hidden>·</span>
                  <span className="font-medium text-foreground">{MODERATION_STATUS_LABELS[item.moderationStatus]}</span>
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
