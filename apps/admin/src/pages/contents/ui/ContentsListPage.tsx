import { useEffect, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { useNavigate } from "@tanstack/react-router";

import {
  CONTENT_TYPE_LABELS,
  CONTENT_VISIBILITY_LABELS,
  MODERATION_STATUS_LABELS,
  useContentListQuery,
  type ContentModerationStatusFilter,
  type ContentSortOption,
  type ContentTypeFilter,
  type ContentVisibilityFilter,
} from "@/entities/admin-content";
import { Pagination } from "@/shared/ui/Pagination";

const TYPE_FILTER_OPTIONS: { value: "all" | ContentTypeFilter; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "character", label: CONTENT_TYPE_LABELS.character },
  { value: "story", label: CONTENT_TYPE_LABELS.story },
];

const VISIBILITY_FILTER_OPTIONS: { value: "all" | ContentVisibilityFilter; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "public", label: CONTENT_VISIBILITY_LABELS.public },
  { value: "link", label: CONTENT_VISIBILITY_LABELS.link },
  { value: "private", label: CONTENT_VISIBILITY_LABELS.private },
];

const MODERATION_FILTER_OPTIONS: { value: "all" | ContentModerationStatusFilter; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "normal", label: MODERATION_STATUS_LABELS.normal },
  { value: "restricted", label: MODERATION_STATUS_LABELS.restricted },
  { value: "deleted", label: MODERATION_STATUS_LABELS.deleted },
];

const SORT_OPTIONS: { value: ContentSortOption; label: string }[] = [
  { value: "recent", label: "최신순" },
  { value: "views", label: "조회수" },
  { value: "chats", label: "채팅수" },
];

/** `SelectItem`의 value가 `string`이라 좁힘이 필요하다. `as` 대신 술어를 쓴다(TS-03, ReportsListPage 동형). */
function isContentType(value: string): value is ContentTypeFilter {
  return TYPE_FILTER_OPTIONS.some((option) => option.value !== "all" && option.value === value);
}
function isContentVisibility(value: string): value is ContentVisibilityFilter {
  return VISIBILITY_FILTER_OPTIONS.some((option) => option.value !== "all" && option.value === value);
}
function isModerationStatus(value: string): value is ContentModerationStatusFilter {
  return MODERATION_FILTER_OPTIONS.some((option) => option.value !== "all" && option.value === value);
}
function isSortOption(value: string): value is ContentSortOption {
  return SORT_OPTIONS.some((option) => option.value === value);
}

const CREATED_AT_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

function formatCount(value: number) {
  return value.toLocaleString("ko-KR");
}

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
  const contentListQuery = useContentListQuery({ page, type, visibility, moderationStatus, q, sort });
  const navigate = useNavigate();
  const [searchInput, setSearchInput] = useState(q ?? "");

  // 뒤로가기 등으로 라우트 search의 q가 외부에서 바뀌어도(리마운트 없이) 입력창이 따라가게 한다.
  useEffect(() => {
    setSearchInput(q ?? "");
  }, [q]);

  const goToDetail = (contentId: string) => void navigate({ to: "/contents/$contentId", params: { contentId } });

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">작품 관리</h1>

        <div className="flex flex-wrap items-center gap-3">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              onFilterChange({ q: searchInput.trim() || undefined });
            }}
            className="flex items-center gap-2"
          >
            <Input
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="작품 이름 검색"
              aria-label="작품 이름 검색"
              className="h-7 w-40 sm:w-56"
            />
            <Button type="submit" variant="outline" size="sm">
              검색
            </Button>
          </form>

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

      {contentListQuery.isPending && <div className="h-64 animate-pulse rounded-xl bg-muted" />}

      {contentListQuery.isError && (
        <p className="text-sm text-destructive-text">작품 목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      )}

      {contentListQuery.data && contentListQuery.data.items.length === 0 && (
        <p className="text-sm text-muted-foreground">조건에 맞는 작품이 없어요.</p>
      )}

      {contentListQuery.data && contentListQuery.data.items.length > 0 && (
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
                    <TableCell>{CREATED_AT_FORMATTER.format(new Date(item.createdAt))}</TableCell>
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
      )}
    </main>
  );
}
