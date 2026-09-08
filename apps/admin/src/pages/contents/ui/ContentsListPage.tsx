import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { useNavigate } from "@tanstack/react-router";
import { useForm } from "react-hook-form";

import {
  CONTENT_TYPE_LABELS,
  CONTENT_TYPE_OPTIONS,
  CONTENT_VISIBILITY_LABELS,
  CONTENT_VISIBILITY_OPTIONS,
  MODERATION_STATUS_LABELS,
  MODERATION_STATUS_OPTIONS,
  isContentType,
  isContentVisibility,
  isModerationStatus,
  useContentListQuery,
  type AdminContentListParams,
  type ContentModerationStatusFilter,
  type ContentSortOption,
  type ContentTypeFilter,
  type ContentVisibilityFilter,
} from "@/entities/admin-content";
import { Pagination } from "@/shared/ui/Pagination";
import { formatCount } from "@/shared/lib/format/formatCount";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";

/** 세 필터 모두 entities가 Record 키에서 도출한 옵션에 `"전체"`만 얹는다 — 멤버를 여기 손으로
 * 나열하면 서버에 값이 늘어도 이 필터만 조용히 빠진다. `SelectItem`의 value가 `string`이라
 * 되받을 때 좁힘이 필요한데, `as` 대신 entities의 술어를 쓴다(TS-03, `ReportsListPage` 동형).
 * `"all"`은 애초에 유효한 멤버가 아니라 술어에서 자연히 걸러진다. */
const TYPE_FILTER_OPTIONS: { value: "all" | ContentTypeFilter; label: string }[] = [
  { value: "all", label: "전체" },
  ...CONTENT_TYPE_OPTIONS,
];

const VISIBILITY_FILTER_OPTIONS: { value: "all" | ContentVisibilityFilter; label: string }[] = [
  { value: "all", label: "전체" },
  ...CONTENT_VISIBILITY_OPTIONS,
];

const MODERATION_FILTER_OPTIONS: { value: "all" | ContentModerationStatusFilter; label: string }[] = [
  { value: "all", label: "전체" },
  ...MODERATION_STATUS_OPTIONS,
];

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

/** techspec.md §4-2, §5-1 — 필터·검색·정렬·페이지는 전부 라우트 search에 담긴다(routes/contents.index.tsx).
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
  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">작품 관리</h1>

        <div className="flex flex-wrap items-center gap-3">
          {/* 뒤로가기 등으로 라우트 search의 q가 외부에서 바뀌면 폼째 리마운트해 입력창을 맞춘다. */}
          <ContentSearchForm
            key={q ?? ""}
            defaultQuery={q}
            onSearch={(nextQuery) => onFilterChange({ q: nextQuery })}
          />

          <Select
            value={type ?? "all"}
            onValueChange={(value) => onFilterChange({ type: isContentType(value) ? value : undefined })}
          >
            <SelectTrigger size="sm" aria-label="종류 필터" className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TYPE_FILTER_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            value={visibility ?? "all"}
            onValueChange={(value) => onFilterChange({ visibility: isContentVisibility(value) ? value : undefined })}
          >
            <SelectTrigger size="sm" aria-label="공개범위 필터" className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {VISIBILITY_FILTER_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            value={moderationStatus ?? "all"}
            onValueChange={(value) => onFilterChange({ moderationStatus: isModerationStatus(value) ? value : undefined })}
          >
            <SelectTrigger size="sm" aria-label="상태 필터" className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {MODERATION_FILTER_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            value={sort ?? "recent"}
            onValueChange={(value) => onFilterChange({ sort: isSortOption(value) ? value : undefined })}
          >
            <SelectTrigger size="sm" aria-label="정렬" className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SORT_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <ContentsTable params={{ page, type, visibility, moderationStatus, q, sort }} onPageChange={onPageChange} />
    </main>
  );
}

/** 검색은 제출만 하고 검증이 없어 zod 스키마 없이 폼 값 타입만 둔다. */
type SearchFormValues = {
  q: string;
};

type ContentSearchFormProps = {
  defaultQuery?: string;
  onSearch: (query: string | undefined) => void;
};

function ContentSearchForm({ defaultQuery, onSearch }: ContentSearchFormProps) {
  const { register, handleSubmit } = useForm<SearchFormValues>({ defaultValues: { q: defaultQuery ?? "" } });

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit(({ q }) => onSearch(q.trim() || undefined))(event);
      }}
      className="flex items-center gap-2"
    >
      <Input placeholder="작품 이름 검색" aria-label="작품 이름 검색" className="h-7 w-40 sm:w-56" {...register("q")} />
      <Button type="submit" variant="outline" size="sm">
        검색
      </Button>
    </form>
  );
}

type ContentsTableProps = {
  params: AdminContentListParams;
  onPageChange: (page: number) => void;
};

/** 헤더(제목·필터)는 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function ContentsTable({ params, onPageChange }: ContentsTableProps) {
  const contentListQuery = useContentListQuery(params);
  const navigate = useNavigate();

  if (contentListQuery.isPending) {
    return <div className="h-64 animate-pulse rounded-xl bg-muted" />;
  }

  if (contentListQuery.isError) {
    return <p className="text-sm text-destructive-text">작품 목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  }

  if (contentListQuery.data.items.length === 0) {
    return <p className="text-sm text-muted-foreground">조건에 맞는 작품이 없어요.</p>;
  }

  const goToDetail = (contentId: string) => void navigate({ to: "/contents/$contentId", params: { contentId } });

  return (
    <>
      <div className="overflow-hidden rounded-xl border border-border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>이름</TableHead>
              <TableHead>종류</TableHead>
              <TableHead>공개범위</TableHead>
              <TableHead>상태</TableHead>
              <TableHead className="text-right">조회수</TableHead>
              <TableHead className="text-right">채팅수</TableHead>
              <TableHead>등록일시</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {contentListQuery.data.items.map((item) => (
              <TableRow
                key={item.id}
                tabIndex={0}
                role="button"
                className="cursor-pointer"
                onClick={() => goToDetail(item.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    goToDetail(item.id);
                  }
                }}
              >
                <TableCell>{item.name || "(이름 없음)"}</TableCell>
                <TableCell className="text-muted-foreground">{CONTENT_TYPE_LABELS[item.type]}</TableCell>
                <TableCell className="text-muted-foreground">
                  {CONTENT_VISIBILITY_LABELS[item.visibility]}
                </TableCell>
                <TableCell>{MODERATION_STATUS_LABELS[item.moderationStatus]}</TableCell>
                <TableCell className="text-right tabular-nums">{formatCount(item.viewCount)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatCount(item.chatCount)}</TableCell>
                <TableCell>{formatDateTime(item.createdAt)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Pagination
        page={contentListQuery.data.page}
        totalPages={contentListQuery.data.totalPages}
        totalCount={contentListQuery.data.totalCount}
        onPageChange={onPageChange}
      />
    </>
  );
}

/** 정렬만 도메인 라벨이 아니라 화면 전용 목록이라 술어가 여기 남는다(`CONTENT_SORT_OPTIONS`는
 * 서버 스키마가 아니라 admin이 정한 값이다). 나머지 셋은 entities의 술어를 그대로 쓴다. */
function isSortOption(value: string): value is ContentSortOption {
  return SORT_OPTIONS.some((option) => option.value === value);
}
