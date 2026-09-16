import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { useForm } from "react-hook-form";

import {
  IMAGE_GENERATION_STATUS_OPTIONS,
  IMAGE_STYLE_OPTIONS,
  imageGenerationStatusLabel,
  imageStyleLabel,
  isImageGenerationStatus,
  isImageStyle,
  useImageGenerationListQuery,
  type AdminImageGenerationListParams,
  type ImageGenerationStatusFilter,
  type ImageGenerationStyleFilter,
} from "@/entities/admin-image-generation";
import { Pagination } from "@/shared/ui/Pagination";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";

// 두 필터 모두 entities가 Record 키에서 도출한 옵션에 `"전체"`만 얹는다 — 멤버를 여기 손으로
// 나열하면 서버에 값이 늘어도 이 필터만 조용히 빠진다(`ContentsListPage` 동형). `SelectItem`의
// value가 `string`이라 되받을 때 좁힘이 필요한데, `as` 대신 entities의 술어를 쓴다(TS-03).
const STATUS_FILTER_OPTIONS: { value: "all" | ImageGenerationStatusFilter; label: string }[] = [
  { value: "all", label: "전체" },
  ...IMAGE_GENERATION_STATUS_OPTIONS,
];

const STYLE_FILTER_OPTIONS: { value: "all" | ImageGenerationStyleFilter; label: string }[] = [
  { value: "all", label: "전체" },
  ...IMAGE_STYLE_OPTIONS,
];

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

/** image-monitoring-goal-prompt.md IM-1, IM-11, IM-12 — 전역 목록은 메타데이터만 보여준다.
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
  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">이미지 생성 관리</h1>

        <div className="flex flex-wrap items-end gap-3">
          {/* 뒤로가기 등으로 라우트 search의 q가 외부에서 바뀌면 폼째 리마운트해 입력창을 맞춘다. */}
          <ImageGenerationSearchForm
            key={q ?? ""}
            defaultQuery={q}
            onSearch={(nextQuery) => onFilterChange({ q: nextQuery })}
          />

          <Select
            value={status ?? "all"}
            onValueChange={(value) => onFilterChange({ status: isImageGenerationStatus(value) ? value : undefined })}
          >
            <SelectTrigger size="sm" aria-label="상태 필터" className="w-28">
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

          <Select
            value={style ?? "all"}
            onValueChange={(value) => onFilterChange({ style: isImageStyle(value) ? value : undefined })}
          >
            <SelectTrigger size="sm" aria-label="스타일 필터" className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STYLE_FILTER_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <div className="flex flex-col gap-1">
            <Label htmlFor="image-generations-from" className="text-xs text-muted-foreground">
              시작일
            </Label>
            <Input
              id="image-generations-from"
              type="date"
              value={from ?? ""}
              max={to}
              onChange={(event) => onFilterChange({ from: event.target.value || undefined })}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="image-generations-to" className="text-xs text-muted-foreground">
              종료일
            </Label>
            <Input
              id="image-generations-to"
              type="date"
              value={to ?? ""}
              min={from}
              onChange={(event) => onFilterChange({ to: event.target.value || undefined })}
            />
          </div>
        </div>
      </div>

      <ImageGenerationsTable params={{ page, q, status, style, from, to }} onPageChange={onPageChange} />
    </main>
  );
}

/** 검색은 제출만 하고 검증이 없어 zod 스키마 없이 폼 값 타입만 둔다. */
type SearchFormValues = {
  q: string;
};

type ImageGenerationSearchFormProps = {
  defaultQuery?: string;
  onSearch: (query: string | undefined) => void;
};

function ImageGenerationSearchForm({ defaultQuery, onSearch }: ImageGenerationSearchFormProps) {
  const { register, handleSubmit } = useForm<SearchFormValues>({ defaultValues: { q: defaultQuery ?? "" } });

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit(({ q }) => onSearch(q.trim() || undefined))(event);
      }}
      className="flex items-center gap-2"
    >
      <Input
        placeholder="닉네임/이메일 검색"
        aria-label="닉네임/이메일 검색"
        className="h-8 w-40 sm:w-56"
        {...register("q")}
      />
      <Button type="submit" variant="outline" size="sm">
        검색
      </Button>
    </form>
  );
}

type ImageGenerationsTableProps = {
  params: AdminImageGenerationListParams;
  onPageChange: (page: number) => void;
};

/** 헤더(제목·필터)는 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function ImageGenerationsTable({ params, onPageChange }: ImageGenerationsTableProps) {
  const imageGenerationListQuery = useImageGenerationListQuery(params);

  if (imageGenerationListQuery.isPending) {
    return <div className="h-64 animate-pulse rounded-xl bg-muted" />;
  }

  if (imageGenerationListQuery.isError) {
    return (
      <p className="text-sm text-destructive-text">
        이미지 생성 내역을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  if (imageGenerationListQuery.data.items.length === 0) {
    return <p className="text-sm text-muted-foreground">조건에 맞는 생성 내역이 없어요.</p>;
  }

  return (
    <>
      <div className="overflow-hidden rounded-xl border border-border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>유저</TableHead>
              <TableHead>상태</TableHead>
              <TableHead>스타일</TableHead>
              <TableHead className="text-right">이미지 수</TableHead>
              <TableHead>생성일시</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {imageGenerationListQuery.data.items.map((item) => (
              <TableRow key={item.id}>
                <TableCell>
                  <div className="flex flex-col">
                    <span>{item.nickname}</span>
                    <span className="text-xs text-muted-foreground">{item.email}</span>
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground">{imageGenerationStatusLabel(item.status)}</TableCell>
                <TableCell className="text-muted-foreground">{imageStyleLabel(item.style)}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {item.completedCount}/{item.requestedCount}
                </TableCell>
                <TableCell>{formatDateTime(item.createdAt)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Pagination
        page={imageGenerationListQuery.data.page}
        totalPages={imageGenerationListQuery.data.totalPages}
        totalCount={imageGenerationListQuery.data.totalCount}
        onPageChange={onPageChange}
      />
    </>
  );
}
