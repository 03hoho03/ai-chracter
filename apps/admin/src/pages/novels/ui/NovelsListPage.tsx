import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";

import {
  NOVEL_MODERATION_STATUS_LABELS,
  NOVEL_MODERATION_STATUS_OPTIONS,
  NOVEL_VISIBILITY_LABELS,
  useNovelListQuery,
  type AdminNovelListParams,
  type AdminNovelListResponse,
  type NovelModerationStatus,
} from "@/entities/admin-novel";
import { formatCount } from "@/shared/lib/format/formatCount";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { DataList, type DataListColumn } from "@/shared/ui/DataList";
import { FilterBar, selectFilter } from "@/shared/ui/FilterBar";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { Pagination } from "@/shared/ui/Pagination";
import { QueryState } from "@/shared/ui/QueryState";

import { HomeNovelCurationStatus } from "./HomeNovelCurationStatus";

type NovelsListPageProps = {
  page: number;
  moderationStatus?: NovelModerationStatus;
  onPageChange: (page: number) => void;
  onModerationStatusChange: (moderationStatus?: NovelModerationStatus) => void;
};

/** 공개한 적 있는 노벨 전부(거둔 것·이용제한된 것 포함). 서버에 이름 검색이 없어 필터는 이용제한 상태 하나다. 필터·페이지는
 * 라우트 search 에 담긴다(routes/novels.index.tsx). */
export function NovelsListPage({ page, moderationStatus, onPageChange, onModerationStatusChange }: NovelsListPageProps) {
  useDocumentTitle("노벨 관리");

  return (
    <PageContainer>
      <PageHeader title="노벨 관리" />

      <FilterBar
        fields={[
          selectFilter({
            id: "moderation-status",
            label: "상태",
            options: NOVEL_MODERATION_STATUS_OPTIONS,
            value: moderationStatus,
            defaultLabel: "전체",
            onChange: onModerationStatusChange,
          }),
        ]}
        onReset={() => onModerationStatusChange(undefined)}
      />

      <HomeNovelCurationStatus />

      <NovelsList
        params={{ page, moderationStatus }}
        onReset={() => onModerationStatusChange(undefined)}
        onPageChange={onPageChange}
      />
    </PageContainer>
  );
}

type NovelListItem = AdminNovelListResponse["items"][number];

/** "독자에게 안 보임"은 공개 상태·이용제한 말고도 게시자 정지·원작 숨김·공개 화 없음으로도 생긴다 — 이유는 상세에서 가른다. */
function NovelStatus({ novel }: { novel: NovelListItem }) {
  return (
    <span className="flex flex-col">
      <span>
        {NOVEL_VISIBILITY_LABELS[novel.visibility]} · {NOVEL_MODERATION_STATUS_LABELS[novel.moderationStatus]}
      </span>
      {!novel.readable && <span className="text-xs text-destructive-text">독자에게 안 보임</span>}
    </span>
  );
}

const COLUMNS: readonly DataListColumn<NovelListItem>[] = [
  { id: "title", header: "제목", isPrimary: true, cell: (item) => item.title || "(제목 없음)" },
  { id: "source", header: "원작", cell: (item) => <span className="text-muted-foreground">{item.sourceTitle}</span> },
  {
    id: "publisher",
    header: "게시자",
    cell: (item) => <span className="text-muted-foreground">{item.publisherNickname ?? "(탈퇴)"}</span>,
  },
  { id: "status", header: "상태", cell: (item) => <NovelStatus novel={item} /> },
  { id: "chapters", header: "공개 화", align: "end", cell: (item) => formatCount(item.chapterCount) },
  { id: "purchases", header: "구매", align: "end", cell: (item) => formatCount(item.purchaseCount) },
  {
    id: "reports",
    header: "대기 신고",
    align: "end",
    cell: (item) => (
      <span className={item.pendingReportCount > 0 ? "font-semibold text-foreground" : "text-muted-foreground"}>
        {formatCount(item.pendingReportCount)}
      </span>
    ),
  },
  { id: "published", header: "최근 공개", cell: (item) => formatDateTime(item.publishedAt) },
];

type NovelsListProps = {
  params: AdminNovelListParams;
  onReset: () => void;
  onPageChange: (page: number) => void;
};

/** 머리(제목·필터)는 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function NovelsList({ params, onReset, onPageChange }: NovelsListProps) {
  const novelListQuery = useNovelListQuery(params);

  return (
    <QueryState
      query={novelListQuery}
      errorMessage="노벨 목록을 불러오지 못했어요."
      isEmpty={(data) => data.items.length === 0}
      getPage={(data) => data}
      empty={
        params.moderationStatus === undefined
          ? { title: "아직 공개된 노벨이 없어요. 게시자가 소설을 노벨에 공개하면 여기에 나타나요." }
          : {
              title: "이 상태의 노벨이 없어요.",
              action: (
                <Button type="button" variant="outline" size="sm" onClick={onReset}>
                  필터 초기화
                </Button>
              ),
            }
      }
    >
      {(data) => (
        <>
          <DataList
            caption="노벨 목록"
            rows={data.items}
            getRowKey={(item) => item.id}
            columns={COLUMNS}
            renderRowTarget={(item, props) => <Link to="/novels/$novelId" params={{ novelId: item.id }} {...props} />}
            card={{
              title: (item) => item.title || "(제목 없음)",
              meta: (item) => (
                <>
                  <span className="wrap-anywhere">{item.sourceTitle}</span>
                  <span aria-hidden>·</span>
                  <span>{NOVEL_VISIBILITY_LABELS[item.visibility]}</span>
                  <span aria-hidden>·</span>
                  <span className="font-medium text-foreground">{NOVEL_MODERATION_STATUS_LABELS[item.moderationStatus]}</span>
                  {!item.readable && (
                    <>
                      <span aria-hidden>·</span>
                      <span className="text-destructive-text">독자에게 안 보임</span>
                    </>
                  )}
                  {item.pendingReportCount > 0 && (
                    <>
                      <span aria-hidden>·</span>
                      <span className="font-medium text-foreground">대기 신고 {formatCount(item.pendingReportCount)}</span>
                    </>
                  )}
                </>
              ),
              trailing: (item) => formatDateTime(item.publishedAt),
            }}
          />

          <Pagination page={data.page} totalPages={data.totalPages} totalCount={data.totalCount} onPageChange={onPageChange} />
        </>
      )}
    </QueryState>
  );
}
