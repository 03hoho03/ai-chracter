import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { Check, X } from "lucide-react";
import { useRef, useState } from "react";

import {
  CREATOR_PAYOUT_APPLICATION_STATUS_LABELS,
  CREATOR_PAYOUT_BLOCK_REASON_LABELS,
  getCreatorPayoutBlockReason,
  useCreatorPayoutApplicationListQuery,
  type AdminCreatorPayoutApplicationItem,
  type CreatorPayoutApplicationStatus,
} from "@/entities/creator-payout-application";
import { ApplicationDecisionActions } from "@/features/decide-creator-payout-application";
import { formatCount } from "@/shared/lib/format/formatCount";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { DataList, type DataListColumn } from "@/shared/ui/DataList";
import { FilterBar, selectFilter } from "@/shared/ui/FilterBar";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { Pagination } from "@/shared/ui/Pagination";
import { QueryState } from "@/shared/ui/QueryState";

/** 서버는 상태 하나만 받고 기본이 대기다 — 필터의 기본 항목이 곧 대기라, 나머지 셋만 고르는 값으로 둔다. */
type NonDefaultStatus = Exclude<CreatorPayoutApplicationStatus, "pending">;

const STATUS_OPTIONS: { value: NonDefaultStatus; label: string }[] = [
  { value: "approved", label: CREATOR_PAYOUT_APPLICATION_STATUS_LABELS.approved },
  { value: "rejected", label: CREATOR_PAYOUT_APPLICATION_STATUS_LABELS.rejected },
  { value: "revoked", label: CREATOR_PAYOUT_APPLICATION_STATUS_LABELS.revoked },
];

const PAGE_TITLE = "정산 신청 검토";

type CreatorPayoutApplicationsPageProps = {
  page: number;
  status?: NonDefaultStatus;
  onPageChange: (page: number) => void;
  onStatusChange: (status?: NonDefaultStatus) => void;
};

export function CreatorPayoutApplicationsPage({
  page,
  status,
  onPageChange,
  onStatusChange,
}: CreatorPayoutApplicationsPageProps) {
  useDocumentTitle(PAGE_TITLE);
  return (
    <PageContainer>
      <PageHeader title={PAGE_TITLE} />

      <FilterBar
        fields={[
          selectFilter({
            id: "status",
            label: "처리상태",
            options: STATUS_OPTIONS,
            value: status,
            defaultLabel: CREATOR_PAYOUT_APPLICATION_STATUS_LABELS.pending,
            onChange: onStatusChange,
          }),
        ]}
        onReset={() => onStatusChange(undefined)}
      />

      <ApplicationsTable
        page={page}
        status={status ?? "pending"}
        onPageChange={onPageChange}
        onReset={() => onStatusChange(undefined)}
      />
    </PageContainer>
  );
}

/** 탈퇴 회원은 서버가 닉네임을 파기해 `null` 로 보낸다. */
function applicantNameOf(item: AdminCreatorPayoutApplicationItem) {
  return item.nickname ?? "탈퇴한 회원";
}

/** 닉네임만으로는 같은 사람의 여러 신청(거절 뒤 재신청)이 구별되지 않아 신청일시를 접근 이름에 더한다. */
function ApplicantTitle({ item }: { item: AdminCreatorPayoutApplicationItem }) {
  return (
    <>
      {applicantNameOf(item)}
      <span className="sr-only">, {formatDateTime(item.appliedAt)} 신청</span>
    </>
  );
}

/** 행의 자격 한 줄. 막혔으면 서버 판정과 같은 순서의 첫 이유 하나만 보인다 — 나머지는 고른 신청의 점검표에 있다. */
function EligibilitySummary({ item }: { item: AdminCreatorPayoutApplicationItem }) {
  const blockReason = getCreatorPayoutBlockReason(item.eligibility);
  if (blockReason === null) return <span className="text-foreground">충족</span>;
  return <span className="font-medium text-destructive-text">{CREATOR_PAYOUT_BLOCK_REASON_LABELS[blockReason]}</span>;
}

const COLUMNS: readonly DataListColumn<AdminCreatorPayoutApplicationItem>[] = [
  { id: "applicant", header: "신청자", isPrimary: true, cell: (item) => <ApplicantTitle item={item} /> },
  { id: "eligibility", header: "지금 자격", cell: (item) => <EligibilitySummary item={item} /> },
  { id: "applied", header: "신청일시", cell: (item) => formatDateTime(item.appliedAt) },
];

const EMPTY_TITLES: Record<CreatorPayoutApplicationStatus, string> = {
  pending: "검토할 정산 신청이 없어요. 크리에이터가 정산을 신청하면 여기에 오래된 순으로 쌓여요.",
  approved: "승인된 정산 신청이 없어요.",
  rejected: "거절된 정산 신청이 없어요.",
  revoked: "승인 취소된 정산 신청이 없어요.",
};

type ApplicationsTableProps = {
  page: number;
  status: CreatorPayoutApplicationStatus;
  onPageChange: (page: number) => void;
  onReset: () => void;
};

/** 헤더(제목·필터)는 로딩·오류에도 남아야 해서 쿼리에 기대는 본문만 갈라낸다. 신청 한 건의 정보가 목록 행에 다
 * 있어 상세 라우트 없이 고른 행을 목록 아래에 펼친다. */
function ApplicationsTable({ page, status, onPageChange, onReset }: ApplicationsTableProps) {
  const listQuery = useCreatorPayoutApplicationListQuery({ page, status });
  const [selectedId, setSelectedId] = useState<string>();
  // 좁은 화면에서는 펼친 신청이 목록 아래 화면 밖이라 고른 순간 그리로 포커스를 옮긴다. 페이지·필터를 바꿔 다시
  // 그려질 때는 옮기지 않게, 마운트가 아니라 고르는 클릭이 남긴 표시로 정한다.
  const shouldFocusDetailRef = useRef(false);
  const focusDetailIfJustSelected = (element: HTMLElement | null) => {
    if (!element || !shouldFocusDetailRef.current) return;
    shouldFocusDetailRef.current = false;
    element.focus();
  };

  return (
    <QueryState
      query={listQuery}
      errorMessage="정산 신청 목록을 불러오지 못했어요."
      isEmpty={(data) => data.items.length === 0}
      getPage={(data) => data}
      empty={
        status === "pending"
          ? { title: EMPTY_TITLES.pending }
          : {
              title: EMPTY_TITLES[status],
              action: (
                <Button type="button" variant="outline" size="sm" onClick={onReset}>
                  대기중 보기
                </Button>
              ),
            }
      }
    >
      {(data) => {
        // 처리하면 목록을 다시 읽어 그 행이 이 상태에서 빠진다 — 그러면 펼친 신청도 함께 닫힌다.
        const selected = data.items.find((item) => item.id === selectedId);

        return (
          <>
            {/* 상세 라우트가 없어 행 대상은 링크가 아니라 고르는 버튼이다. 고른 행은 `aria-current` 와 체크 글리프로 알린다. */}
            <DataList
              caption="정산 신청 목록"
              rows={data.items}
              getRowKey={(item) => item.id}
              columns={COLUMNS}
              isRowSelected={(item) => item.id === selectedId}
              renderRowTarget={(item, props) => (
                <button
                  type="button"
                  aria-current={item.id === selectedId || undefined}
                  onClick={() => {
                    shouldFocusDetailRef.current = item.id !== selectedId;
                    setSelectedId(item.id);
                  }}
                  {...props}
                />
              )}
              card={{
                title: (item) => <ApplicantTitle item={item} />,
                meta: (item) => <EligibilitySummary item={item} />,
                trailing: (item) => formatDateTime(item.appliedAt),
              }}
            />

            <Pagination
              page={data.page}
              totalPages={data.totalPages}
              totalCount={data.totalCount}
              onPageChange={onPageChange}
            />

            {selected && (
              <section
                key={selected.id}
                ref={focusDetailIfJustSelected}
                tabIndex={-1}
                aria-label="고른 정산 신청"
                className="@container flex flex-col gap-5 rounded-xl border border-border bg-card p-4 outline-none sm:p-6"
              >
                <ApplicationDetail application={selected} />
              </section>
            )}
          </>
        );
      }}
    </QueryState>
  );
}

function ApplicationDetail({ application }: { application: AdminCreatorPayoutApplicationItem }) {
  const applicantName = applicantNameOf(application);
  const { withdrawn } = application.eligibility;

  return (
    <>
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground">
            {CREATOR_PAYOUT_APPLICATION_STATUS_LABELS[application.status]}
          </span>
          <span className="text-sm text-muted-foreground">{formatDateTime(application.appliedAt)} 신청</span>
        </div>
        <h2 className="text-lg font-semibold break-all text-foreground">{applicantName}</h2>
        {/* 탈퇴 회원은 회원 상세가 404 라 링크를 두지 않는다 — 이 화면이 처리에 필요한 값을 다 가진다. */}
        {withdrawn ? (
          <p className="text-sm break-keep text-muted-foreground">
            탈퇴한 회원이라 회원 상세가 없어요.
          </p>
        ) : (
          <Link
            to="/users/$userId"
            params={{ userId: application.userId }}
            className="admin-hit-area w-fit text-sm font-medium text-primary hover:underline focus-visible:underline"
          >
            회원 상세 보기
          </Link>
        )}
      </div>

      <EligibilityChecklist application={application} />

      <DecisionHistory application={application} />

      <ApplicationDecisionActions application={application} applicantName={applicantName} />
    </>
  );
}

/** 지금 자격 점검표. 승인 때 서버가 같은 다섯 가지를 다시 본다. 통과·미달을 색만이 아니라 글리프와 문장으로도 가른다. */
function EligibilityChecklist({ application }: { application: AdminCreatorPayoutApplicationItem }) {
  const { eligibility } = application;
  const items = [
    { id: "withdrawn", ok: !eligibility.withdrawn, label: eligibility.withdrawn ? "탈퇴함" : "탈퇴 안 함" },
    { id: "suspended", ok: !eligibility.suspended, label: eligibility.suspended ? "이용 정지 중" : "이용 정지 아님" },
    {
      id: "identity",
      ok: eligibility.identityVerified,
      label: eligibility.identityVerified ? "본인인증 완료" : "본인인증 안 함",
    },
    { id: "adult", ok: eligibility.adult, label: eligibility.adult ? "만 19세 이상" : "만 19세 미만이거나 확인 불가" },
    {
      id: "published",
      ok: eligibility.publishedCount > 0,
      label: `발행 작품 ${formatCount(eligibility.publishedCount)}개`,
    },
  ];

  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-sm font-medium text-foreground">지금 자격</h3>
      <ul className="grid gap-1.5 @xl:grid-cols-2">
        {items.map((item) => (
          <li
            key={item.id}
            className={cn(
              "flex items-center gap-2 text-sm",
              item.ok ? "text-foreground" : "font-medium text-destructive-text",
            )}
          >
            {item.ok ? (
              <Check aria-hidden className="size-4 shrink-0 text-muted-foreground" />
            ) : (
              <X aria-hidden className="size-4 shrink-0" />
            )}
            <span>
              {item.label}
              {!item.ok && <span className="sr-only"> (미달)</span>}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** 처리 이력. 승인 메모·승인 취소 사유는 감사 기록에만 있어 응답에 없다 — 신청자에게 보인 거절 사유만 여기 보인다. */
function DecisionHistory({ application }: { application: AdminCreatorPayoutApplicationItem }) {
  if (application.status === "pending" || !application.decidedAt) return null;

  const decidedLabel = application.status === "rejected" ? "거절일시" : "승인일시";
  return (
    <dl className="grid gap-x-6 gap-y-3 text-sm @xl:grid-cols-2">
      <div className="flex flex-col gap-0.5">
        <dt className="text-muted-foreground">{decidedLabel}</dt>
        <dd className="text-foreground tabular-nums">{formatDateTime(application.decidedAt)}</dd>
      </div>
      {application.revokedAt && (
        <div className="flex flex-col gap-0.5">
          <dt className="text-muted-foreground">승인 취소일시</dt>
          <dd className="text-foreground tabular-nums">{formatDateTime(application.revokedAt)}</dd>
        </div>
      )}
      {application.status === "rejected" && (
        <div className="flex flex-col gap-0.5 @xl:col-span-2">
          <dt className="text-muted-foreground">거절 사유 (신청자에게 보임)</dt>
          <dd className="whitespace-pre-wrap break-keep text-foreground wrap-anywhere">
            {application.decisionReason || "-"}
          </dd>
        </div>
      )}
    </dl>
  );
}
