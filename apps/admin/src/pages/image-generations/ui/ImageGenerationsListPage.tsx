import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";

import {
  IMAGE_GENERATION_STATUS_OPTIONS,
  IMAGE_STYLE_VALUES,
  imageGenerationStatusLabel,
  useImageGenerationListQuery,
  useImageStyleOptionsQuery,
  type AdminImageGenerationListParams,
  type AdminImageGenerationListResponse,
  type ImageGenerationStatusFilter,
  type ImageGenerationStyleFilter,
} from "@/entities/admin-image-generation";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { DataList, type DataListColumn } from "@/shared/ui/DataList";
import { dateRangeFilter, FilterBar, selectFilter } from "@/shared/ui/FilterBar";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { Pagination } from "@/shared/ui/Pagination";
import { QueryState } from "@/shared/ui/QueryState";

type ImageGenerationFilterPatch = {
  q?: string;
  status?: ImageGenerationStatusFilter;
  style?: ImageGenerationStyleFilter;
  from?: string;
  to?: string;
};

type ImageGenerationsListPageProps = {
  page: number;
  q?: string;
  status?: ImageGenerationStatusFilter;
  style?: ImageGenerationStyleFilter;
  from?: string;
  to?: string;
  onPageChange: (page: number) => void;
  onFilterChange: (patch: ImageGenerationFilterPatch) => void;
};

// 스타일 필터의 이름은 목록 응답(`styleOptions`)에서 온다. 첫 응답 전에는 이름이 없으므로 id 를
// 그대로 보인다 — 선택지를 비워 두면 주소에 담긴 선택 값이 트리거에 안 보인다.
const STYLE_ID_FALLBACK_OPTIONS = IMAGE_STYLE_VALUES.map((id) => ({ id, name: id }));

/** 전역 목록은 메타데이터만 보여준다. 행은 그 유저의 생성 이미지 열람 화면으로 가고, 이 목록에서 들어갔다는 것을
 * URL(`from=image-generations`)에 실어 그 화면의 "목록으로"·취소가 이 목록으로 돌아온다.
 * 필터·검색·페이지는 전부 라우트 search에 담긴다(routes/image-generations.index.tsx). */
export function ImageGenerationsListPage({
  page,
  q,
  status,
  style,
  from,
  to,
  onPageChange,
  onFilterChange,
}: ImageGenerationsListPageProps) {
  useDocumentTitle("이미지 생성 관리");
  const styleOptionsQuery = useImageStyleOptionsQuery({ page, q, status, style, from, to });
  const styleOptions = (styleOptionsQuery.data ?? STYLE_ID_FALLBACK_OPTIONS).map((option) => ({
    value: option.id,
    label: option.name,
  }));
  const resetFilters = () => onFilterChange({ status: undefined, style: undefined, from: undefined, to: undefined });
  const hasCondition = [q, status, style, from, to].some((value) => value !== undefined);

  return (
    <PageContainer>
      <PageHeader title="이미지 생성 관리" />

      <FilterBar
        search={{
          label: "닉네임/이메일 검색",
          placeholder: "닉네임/이메일 검색",
          value: q,
          onSubmit: (nextQuery) => onFilterChange({ q: nextQuery }),
        }}
        fields={[
          selectFilter({
            id: "status",
            label: "상태",
            options: IMAGE_GENERATION_STATUS_OPTIONS,
            value: status,
            defaultLabel: "전체",
            onChange: (value) => onFilterChange({ status: value }),
          }),
          selectFilter({
            id: "style",
            label: "스타일",
            options: styleOptions,
            value: style,
            defaultLabel: "전체",
            onChange: (value) => onFilterChange({ style: value }),
          }),
          dateRangeFilter({ id: "period", label: "기간", from, to, onChange: onFilterChange }),
        ]}
        onReset={resetFilters}
      />

      <ImageGenerationsList
        params={{ page, q, status, style, from, to }}
        hasCondition={hasCondition}
        onReset={() => onFilterChange({ q: undefined, status: undefined, style: undefined, from: undefined, to: undefined })}
        onPageChange={onPageChange}
      />
    </PageContainer>
  );
}

type ImageGenerationListItem = AdminImageGenerationListResponse["items"][number];

const COLUMNS: readonly DataListColumn<ImageGenerationListItem>[] = [
  {
    id: "user",
    header: "유저",
    isPrimary: true,
    cell: (item) => (
      <span className="flex flex-col">
        <span>{item.nickname}</span>
        <span className="text-xs text-muted-foreground">{item.email}</span>
      </span>
    ),
  },
  { id: "status", header: "상태", cell: (item) => <span className="text-muted-foreground">{imageGenerationStatusLabel(item.status)}</span> },
  { id: "style", header: "스타일", cell: (item) => <span className="text-muted-foreground">{item.styleName ?? item.style}</span> },
  { id: "count", header: "이미지 수", align: "end", cell: (item) => `${item.completedCount}/${item.requestedCount}` },
  { id: "created", header: "생성일시", cell: (item) => formatDateTime(item.createdAt) },
];

type ImageGenerationsListProps = {
  params: AdminImageGenerationListParams;
  /** 필터·검색어가 하나라도 걸렸는지 — 빈 결과의 안내가 갈린다. */
  hasCondition: boolean;
  onReset: () => void;
  onPageChange: (page: number) => void;
};

/** 헤더(제목·필터)는 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function ImageGenerationsList({ params, hasCondition, onReset, onPageChange }: ImageGenerationsListProps) {
  const imageGenerationListQuery = useImageGenerationListQuery(params);

  return (
    <QueryState
      query={imageGenerationListQuery}
      errorMessage="이미지 생성 내역을 불러오지 못했어요."
      isEmpty={(data) => data.items.length === 0}
      getPage={(data) => data}
      empty={
        hasCondition
          ? {
              title: "조건에 맞는 요청이 없어요.",
              action: (
                <Button type="button" variant="outline" size="sm" onClick={onReset}>
                  검색·필터 초기화
                </Button>
              ),
            }
          : { title: "생성 요청이 없어요." }
      }
    >
      {(data) => (
        <>
          <DataList
            caption="이미지 생성 목록"
            rows={data.items}
            getRowKey={(item) => item.id}
            columns={COLUMNS}
            renderRowTarget={(item, props) => (
              <Link
                to="/users/$userId/image-generations"
                params={{ userId: item.userId }}
                search={{ from: "image-generations" }}
                {...props}
              />
            )}
            card={{
              title: (item) => item.nickname,
              meta: (item) => (
                <>
                  <span className="wrap-anywhere">{item.email}</span>
                  <span aria-hidden>·</span>
                  <span className="font-medium text-foreground">{imageGenerationStatusLabel(item.status)}</span>
                  <span aria-hidden>·</span>
                  <span>{item.styleName ?? item.style}</span>
                  <span aria-hidden>·</span>
                  <span className="tabular-nums">
                    {item.completedCount}/{item.requestedCount}장
                  </span>
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
