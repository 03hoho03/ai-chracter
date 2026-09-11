import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { useNavigate } from "@tanstack/react-router";
import { useForm } from "react-hook-form";

import { useUserListQuery, type AdminUserListParams } from "@/entities/admin-user";
import { Pagination } from "@/shared/ui/Pagination";
import { formatCount } from "@/shared/lib/format/formatCount";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";

type SuspendedFilterValue = "all" | "normal" | "suspended";

const SUSPENDED_FILTER_OPTIONS: { value: SuspendedFilterValue; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "normal", label: "정상" },
  { value: "suspended", label: "정지" },
];

type UsersFilterPatch = {
  q?: string;
  suspended?: boolean;
};

type UsersListPageProps = {
  page: number;
  q?: string;
  suspended?: boolean;
  onPageChange: (page: number) => void;
  onFilterChange: (patch: UsersFilterPatch) => void;
};

/** ContentsListPage 동형 — 필터·검색·페이지는 전부 라우트 search에 담긴다(routes/users.index.tsx).
 * 이메일·닉네임 검색은 제출 기반이다 — 타이핑마다 요청을 날리지 않는다. `sort`는 BE에 없어 만들지 않는다. */
export function UsersListPage({ page, q, suspended, onPageChange, onFilterChange }: UsersListPageProps) {
  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">유저 관리</h1>

        <div className="flex flex-wrap items-center gap-3">
          {/* 뒤로가기 등으로 라우트 search의 q가 외부에서 바뀌면 폼째 리마운트해 입력창을 맞춘다. */}
          <UserSearchForm key={q ?? ""} defaultQuery={q} onSearch={(nextQuery) => onFilterChange({ q: nextQuery })} />

          <Select
            value={suspendedFilterValueOf(suspended)}
            onValueChange={(value) => {
              if (!isSuspendedFilterValue(value)) return;
              onFilterChange({ suspended: value === "all" ? undefined : value === "suspended" });
            }}
          >
            <SelectTrigger size="sm" aria-label="정지 상태 필터" className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SUSPENDED_FILTER_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <UsersTable params={{ page, q, suspended }} onPageChange={onPageChange} />
    </main>
  );
}

/** 검색은 제출만 하고 검증이 없어 zod 스키마 없이 폼 값 타입만 둔다. */
type SearchFormValues = {
  q: string;
};

type UserSearchFormProps = {
  defaultQuery?: string;
  onSearch: (query: string | undefined) => void;
};

function UserSearchForm({ defaultQuery, onSearch }: UserSearchFormProps) {
  const { register, handleSubmit } = useForm<SearchFormValues>({ defaultValues: { q: defaultQuery ?? "" } });

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit(({ q }) => onSearch(q.trim() || undefined))(event);
      }}
      className="flex items-center gap-2"
    >
      {/* 옆 Button(size="sm")이 32px라 그 높이에 맞춘다(design-system-progress.md P-3-8). */}
      <Input placeholder="이메일 또는 닉네임 검색" aria-label="이메일 또는 닉네임 검색" className="h-8 w-48 sm:w-64" {...register("q")} />
      <Button type="submit" variant="outline" size="sm">
        검색
      </Button>
    </form>
  );
}

type UsersTableProps = {
  params: AdminUserListParams;
  onPageChange: (page: number) => void;
};

/** 헤더(제목·필터)는 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function UsersTable({ params, onPageChange }: UsersTableProps) {
  const userListQuery = useUserListQuery(params);
  const navigate = useNavigate();

  if (userListQuery.isPending) {
    return <div className="h-64 animate-pulse rounded-xl bg-muted" />;
  }

  if (userListQuery.isError) {
    return <p className="text-sm text-destructive-text">유저 목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  }

  if (userListQuery.data.items.length === 0) {
    return <p className="text-sm text-muted-foreground">조건에 맞는 유저가 없어요.</p>;
  }

  const goToDetail = (userId: string) => void navigate({ to: "/users/$userId", params: { userId } });

  return (
    <>
      <div className="overflow-hidden rounded-xl border border-border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>이메일</TableHead>
              <TableHead>닉네임</TableHead>
              <TableHead>상태</TableHead>
              <TableHead className="text-right">작품수</TableHead>
              <TableHead className="text-right">채팅방수</TableHead>
              <TableHead>가입일시</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {userListQuery.data.items.map((item) => (
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
                <TableCell>{item.email}</TableCell>
                <TableCell className="text-muted-foreground">{item.nickname}</TableCell>
                <TableCell>{item.suspendedAt ? "정지" : "정상"}</TableCell>
                <TableCell className="text-right tabular-nums">{formatCount(item.contentCount)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatCount(item.chatRoomCount)}</TableCell>
                <TableCell>{formatDateTime(item.createdAt)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Pagination
        page={userListQuery.data.page}
        totalPages={userListQuery.data.totalPages}
        totalCount={userListQuery.data.totalCount}
        onPageChange={onPageChange}
      />
    </>
  );
}

/** `SelectItem`의 value가 `string`이라 좁힘이 필요하다. `as` 대신 술어를 쓴다(TS-03, ContentsListPage 동형). */
function isSuspendedFilterValue(value: string): value is SuspendedFilterValue {
  return SUSPENDED_FILTER_OPTIONS.some((option) => option.value === value);
}

function suspendedFilterValueOf(suspended: boolean | undefined): SuspendedFilterValue {
  if (suspended === undefined) return "all";
  return suspended ? "suspended" : "normal";
}
