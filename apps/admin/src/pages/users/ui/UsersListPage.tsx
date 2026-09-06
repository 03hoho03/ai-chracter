import { useEffect, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { useNavigate } from "@tanstack/react-router";

import { useUserListQuery } from "@/entities/admin-user";
import { Pagination } from "@/shared/ui/Pagination";

type SuspendedFilterValue = "all" | "normal" | "suspended";

const SUSPENDED_FILTER_OPTIONS: { value: SuspendedFilterValue; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "normal", label: "정상" },
  { value: "suspended", label: "정지" },
];

/** `SelectItem`의 value가 `string`이라 좁힘이 필요하다. `as` 대신 술어를 쓴다(TS-03, ContentsListPage 동형). */
function isSuspendedFilterValue(value: string): value is SuspendedFilterValue {
  return SUSPENDED_FILTER_OPTIONS.some((option) => option.value === value);
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

function suspendedFilterValueOf(suspended: boolean | undefined): SuspendedFilterValue {
  if (suspended === undefined) return "all";
  return suspended ? "suspended" : "normal";
}

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
  const userListQuery = useUserListQuery({ page, q, suspended });
  const navigate = useNavigate();
  const [searchInput, setSearchInput] = useState(q ?? "");

  // 뒤로가기 등으로 라우트 search의 q가 외부에서 바뀌어도(리마운트 없이) 입력창이 따라가게 한다.
  useEffect(() => {
    setSearchInput(q ?? "");
  }, [q]);

  const goToDetail = (userId: string) => void navigate({ to: "/users/$userId", params: { userId } });

  const suspendedFilterValue = suspendedFilterValueOf(suspended);

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">유저 관리</h1>

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
              placeholder="이메일 또는 닉네임 검색"
              aria-label="이메일 또는 닉네임 검색"
              className="h-7 w-48 sm:w-64"
            />
            <Button type="submit" variant="outline" size="sm">
              검색
            </Button>
          </form>

          <Select
            value={suspendedFilterValue}
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

      {userListQuery.isPending && <div className="h-64 animate-pulse rounded-xl bg-muted" />}

      {userListQuery.isError && (
        <p className="text-sm text-destructive-text">유저 목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      )}

      {userListQuery.data && userListQuery.data.items.length === 0 && (
        <p className="text-sm text-muted-foreground">조건에 맞는 유저가 없어요.</p>
      )}

      {userListQuery.data && userListQuery.data.items.length > 0 && (
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
                    <TableCell>{CREATED_AT_FORMATTER.format(new Date(item.createdAt))}</TableCell>
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
      )}
    </main>
  );
}
