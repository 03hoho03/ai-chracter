import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";

import { useUserListQuery, type AdminUserListParams, type AdminUserListResponse } from "@/entities/admin-user";
import { formatCount } from "@/shared/lib/format/formatCount";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { DataList, type DataListColumn } from "@/shared/ui/DataList";
import { FilterBar, selectFilter } from "@/shared/ui/FilterBar";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { Pagination } from "@/shared/ui/Pagination";
import { QueryState } from "@/shared/ui/QueryState";

const SUSPENDED_OPTIONS = [
  { value: "normal", label: "정상" },
  { value: "suspended", label: "정지" },
] as const;

/** BE는 `beta=false`(미지정만)도 받지만 쓰는 일은 "베타 참가자만 보기"뿐이라 선택지를 하나만 둔다
 * (라우트 search도 `true`만 받는다). */
const BETA_OPTIONS = [{ value: "beta", label: "베타만" }] as const;

type UsersFilterPatch = {
  q?: string;
  suspended?: boolean;
  beta?: true;
};

type UsersListPageProps = {
  page: number;
  q?: string;
  suspended?: boolean;
  beta?: true;
  onPageChange: (page: number) => void;
  onFilterChange: (patch: UsersFilterPatch) => void;
};

/** ContentsListPage 동형 — 필터·검색·페이지는 전부 라우트 search에 담긴다(routes/users.index.tsx).
 * 이메일·닉네임 검색은 제출 기반이다 — 타이핑마다 요청을 날리지 않는다. `sort`는 BE에 없어 만들지 않는다. */
export function UsersListPage({ page, q, suspended, beta, onPageChange, onFilterChange }: UsersListPageProps) {
  const resetFilters = () => onFilterChange({ suspended: undefined, beta: undefined });
  const hasCondition = suspended !== undefined || beta !== undefined || q !== undefined;

  return (
    <PageContainer>
      <PageHeader title="유저 관리" />

      <FilterBar
        search={{
          label: "이메일 또는 닉네임 검색",
          placeholder: "이메일 또는 닉네임 검색",
          value: q,
          onSubmit: (nextQuery) => onFilterChange({ q: nextQuery }),
        }}
        fields={[
          // URL 의 `suspended` 는 불리언이라 셀렉트 값(문자열)과 오가며 바꾼다 — 기본값 "전체"는 `undefined`.
          selectFilter({
            id: "suspended",
            label: "정지 상태",
            options: SUSPENDED_OPTIONS,
            value: suspendedFilterValueOf(suspended),
            defaultLabel: "전체",
            onChange: (value) => onFilterChange({ suspended: value === undefined ? undefined : value === "suspended" }),
          }),
          selectFilter({
            id: "beta",
            label: "베타",
            options: BETA_OPTIONS,
            value: beta ? "beta" : undefined,
            defaultLabel: "전체",
            onChange: (value) => onFilterChange({ beta: value === "beta" ? true : undefined }),
          }),
        ]}
        onReset={resetFilters}
      />

      <UsersList
        params={{ page, q, suspended, beta }}
        hasCondition={hasCondition}
        onReset={() => onFilterChange({ suspended: undefined, beta: undefined, q: undefined })}
        onPageChange={onPageChange}
      />
    </PageContainer>
  );
}

type UserListItem = AdminUserListResponse["items"][number];

/** 정지와 베타는 별개 축이라 같은 칸에 덧붙이되, 기본 상태(미지정)엔 아무것도 안 붙인다. */
function UserStatus({ item }: { item: UserListItem }) {
  return (
    <>
      {item.suspendedAt ? "정지" : "정상"}
      {!!item.betaJoinedAt && <span className="text-muted-foreground"> · 베타</span>}
    </>
  );
}

const COLUMNS: readonly DataListColumn<UserListItem>[] = [
  { id: "email", header: "이메일", isPrimary: true, cell: (item) => item.email },
  { id: "nickname", header: "닉네임", cell: (item) => <span className="text-muted-foreground">{item.nickname}</span> },
  { id: "status", header: "상태", cell: (item) => <UserStatus item={item} /> },
  { id: "contents", header: "작품수", align: "end", cell: (item) => formatCount(item.contentCount) },
  { id: "chat-rooms", header: "채팅방수", align: "end", cell: (item) => formatCount(item.chatRoomCount) },
  { id: "created", header: "가입일시", cell: (item) => formatDateTime(item.createdAt) },
];

type UsersListProps = {
  params: AdminUserListParams;
  /** 필터·검색어가 하나라도 걸렸는지 — 빈 결과의 안내가 갈린다. */
  hasCondition: boolean;
  onReset: () => void;
  onPageChange: (page: number) => void;
};

/** 헤더(제목·필터)는 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function UsersList({ params, hasCondition, onReset, onPageChange }: UsersListProps) {
  const userListQuery = useUserListQuery(params);

  return (
    <QueryState
      query={userListQuery}
      errorMessage="유저 목록을 불러오지 못했어요."
      isEmpty={(data) => data.items.length === 0}
      empty={
        hasCondition
          ? {
              title: "검색·필터에 맞는 유저가 없어요. 이메일 일부로도 찾을 수 있어요.",
              action: (
                <Button type="button" variant="outline" size="sm" onClick={onReset}>
                  검색·필터 초기화
                </Button>
              ),
            }
          : { title: "가입한 유저가 없어요." }
      }
    >
      {(data) => (
        <>
          <DataList
            caption="유저 목록"
            rows={data.items}
            getRowKey={(item) => item.id}
            columns={COLUMNS}
            renderRowTarget={(item, props) => <Link to="/users/$userId" params={{ userId: item.id }} {...props} />}
            card={{
              title: (item) => item.email,
              meta: (item) => (
                <>
                  <span className="wrap-anywhere">{item.nickname}</span>
                  <span aria-hidden>·</span>
                  <span className="font-medium text-foreground">
                    <UserStatus item={item} />
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

function suspendedFilterValueOf(suspended: boolean | undefined) {
  if (suspended === undefined) return undefined;
  return suspended ? "suspended" : "normal";
}
