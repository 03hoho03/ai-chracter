import { type ReactNode, useId, useState } from "react";
import type { components } from "@ai-character-chat/api-types";
import { Markdown } from "@ai-character-chat/ui/components/markdown";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronDown, FileQuestion } from "lucide-react";

import {
  type ChangeNoticeEntry,
  LEGAL_DOCUMENT_LABEL,
  type LegalDocumentKind,
  toChangeNoticeEntries,
  useLegalChangesQuery,
  useLegalDocumentQuery,
  useLegalUpcomingDocumentQuery,
} from "@/entities/legal";
import { formatKstDate } from "@/shared/lib/time/formatKstDate";

type LegalUpcomingSummary = components["schemas"]["LegalUpcomingSummary"];

/** 법적 문서(`LegalDocumentKind` 전부 — `/terms`·`/privacy` 등) 공용 페이지 — 라우트들이 `kind`만 다를 뿐
 * 조회·렌더 로직이 완전히 같아 페이지를 하나로 두고 라우트 파일에서 kind만 주입한다(routes/terms.tsx 등). */
export function LegalDocumentPage({ kind }: { kind: LegalDocumentKind }) {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-4 sm:px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight text-foreground">{LEGAL_DOCUMENT_LABEL[kind]}</h1>
      <LegalDocumentBody kind={kind} />
    </main>
  );
}

type LegalDocumentBodyProps = {
  kind: LegalDocumentKind;
};

/** 제목은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function LegalDocumentBody({ kind }: LegalDocumentBodyProps) {
  const documentQuery = useLegalDocumentQuery(kind);

  if (documentQuery.isPending) {
    return <LegalDocumentSkeleton />;
  }

  if (documentQuery.isError) {
    if (documentQuery.error.status === 404) {
      return (
        <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
          <FileQuestion aria-hidden className="size-8 text-muted-foreground" />
          <p className="text-lg font-semibold text-foreground">아직 게시된 문서가 없어요</p>
          <p className="text-sm text-muted-foreground">잠시 후 다시 확인해주세요.</p>
        </div>
      );
    }

    return (
      <p className="text-sm text-destructive-text">
        {LEGAL_DOCUMENT_LABEL[kind]}을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  const legalDocument = documentQuery.data;
  return (
    <>
      {/* 시행일 전에 미리 게시한 판을 알린다 — 그날까지는 아래의 지금 판이 적용된다. */}
      {legalDocument.upcoming !== null && <UpcomingNotice kind={kind} upcoming={legalDocument.upcoming} />}
      {/* 날짜는 게시(공지) 시각이 아니라 이 판이 적용되기 시작한 시행일이다. 미리 게시한 판은 공지일과 시행일이 다르다. */}
      <p className="text-xs text-muted-foreground">
        {legalDocument.version} 판 · {formatKstDate(legalDocument.effectiveAt)} 시행
      </p>
      <Markdown content={legalDocument.bodyMarkdown} />
      <ChangeHistory kind={kind} />
    </>
  );
}

type UpcomingNoticeProps = {
  kind: LegalDocumentKind;
  upcoming: LegalUpcomingSummary;
};

function UpcomingNotice({ kind, upcoming }: UpcomingNoticeProps) {
  const [isNoticeExpanded, setIsNoticeExpanded] = useState(false);
  const [isFullTextExpanded, setIsFullTextExpanded] = useState(false);
  const noticePanelId = useId();
  const fullTextPanelId = useId();
  const effectiveDate = formatKstDate(upcoming.effectiveAt);

  return (
    <section aria-label="시행 예정 판" className="flex flex-col gap-3 rounded-xl border border-border p-4">
      <div className="flex flex-col gap-1">
        <p className="text-sm font-semibold text-foreground">{effectiveDate} 시행 예정</p>
        <p className="text-xs break-keep text-muted-foreground">
          {upcoming.version} 판을 미리 알려요. 시행일 전까지는 아래의 지금 판이 적용돼요.
        </p>
      </div>
      <div className="flex flex-wrap gap-x-4">
        <DisclosureToggle
          isExpanded={isNoticeExpanded}
          panelId={noticePanelId}
          onToggle={() => setIsNoticeExpanded((previous) => !previous)}
        >
          변경 안내 {isNoticeExpanded ? "접기" : "보기"}
        </DisclosureToggle>
        <DisclosureToggle
          isExpanded={isFullTextExpanded}
          panelId={fullTextPanelId}
          onToggle={() => setIsFullTextExpanded((previous) => !previous)}
        >
          예정 전문 {isFullTextExpanded ? "접기" : "보기"}
        </DisclosureToggle>
      </div>
      {isNoticeExpanded && (
        <div id={noticePanelId} className="border-t border-border pt-3">
          {upcoming.changeNotice !== null && upcoming.changeNotice.trim() !== "" ? (
            <Markdown content={upcoming.changeNotice} />
          ) : (
            <p className="text-sm break-keep text-muted-foreground">이 판은 변경 안내가 없습니다. 예정 전문을 확인해 주세요.</p>
          )}
        </div>
      )}
      {isFullTextExpanded && (
        <div id={fullTextPanelId} className="border-t border-border pt-3">
          <UpcomingFullText kind={kind} />
        </div>
      )}
    </section>
  );
}

/** 예정 판 전문은 펼칠 때 처음 받는다 — 수만 자라 예정 판이 있다는 것만으로 모든 방문자에게 받게 하지 않는다. */
function UpcomingFullText({ kind }: { kind: LegalDocumentKind }) {
  const upcomingQuery = useLegalUpcomingDocumentQuery(kind, true);

  if (upcomingQuery.isPending) return <LegalDocumentSkeleton />;
  if (upcomingQuery.isError) {
    // 404 는 펼친 사이 예정 판이 시행되거나 철회된 경우다.
    return (
      <p className="text-sm break-keep text-destructive-text">
        {upcomingQuery.error.status === 404
          ? "예정 판이 시행되었거나 철회됐어요. 페이지를 새로 고쳐 주세요."
          : "예정 전문을 불러오지 못했어요. 잠시 후 다시 시도해주세요."}
      </p>
    );
  }
  return <Markdown content={upcomingQuery.data.bodyMarkdown} />;
}

/** 시행된 판들의 변경 안내(최신 판부터). 판마다 안내가 길어 접어 두고 고른 판만 펼친다. */
function ChangeHistory({ kind }: { kind: LegalDocumentKind }) {
  const headingId = useId();
  const changesQuery = useLegalChangesQuery(kind);
  const [expandedVersion, setExpandedVersion] = useState<string | null>(null);

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3 border-t border-border pt-6">
      <h2 id={headingId} className="text-lg font-semibold text-foreground">
        변경 이력
      </h2>
      <ChangeHistoryList
        changesQuery={changesQuery}
        expandedVersion={expandedVersion}
        onToggle={(version) => setExpandedVersion((previous) => (previous === version ? null : version))}
      />
    </section>
  );
}

type ChangeHistoryListProps = {
  changesQuery: ReturnType<typeof useLegalChangesQuery>;
  expandedVersion: string | null;
  onToggle: (version: string) => void;
};

function ChangeHistoryList({ changesQuery, expandedVersion, onToggle }: ChangeHistoryListProps) {
  if (changesQuery.isPending) return <LegalDocumentSkeleton />;
  if (changesQuery.isError) {
    return <p className="text-sm text-destructive-text">변경 이력을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  }

  const entries = toChangeNoticeEntries(changesQuery.data.items);
  return (
    <ol className="flex flex-col">
      {entries.map((entry, index) => (
        <ChangeHistoryRow
          key={entry.version}
          entry={entry}
          isCurrent={index === 0}
          isExpanded={expandedVersion === entry.version}
          onToggle={() => onToggle(entry.version)}
        />
      ))}
    </ol>
  );
}

type ChangeHistoryRowProps = {
  entry: ChangeNoticeEntry;
  isCurrent: boolean;
  isExpanded: boolean;
  onToggle: () => void;
};

function ChangeHistoryRow({ entry, isCurrent, isExpanded, onToggle }: ChangeHistoryRowProps) {
  const panelId = useId();

  return (
    <li className="flex flex-col border-b border-border last:border-b-0">
      <button
        type="button"
        aria-expanded={isExpanded}
        aria-controls={panelId}
        onClick={onToggle}
        className="-mx-2 flex min-h-11 items-center gap-2 rounded-md px-2 py-2 text-left text-sm outline-none hover:bg-muted focus-visible:outline-1 focus-visible:outline-solid focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50 motion-safe:transition-colors"
      >
        <span className="font-medium text-foreground tabular-nums">{entry.version} 판</span>
        <span className="min-w-0 flex-1 text-muted-foreground tabular-nums">{entry.effectiveDate} 시행</span>
        {isCurrent && <span className="shrink-0 text-xs font-medium text-foreground">지금 판</span>}
        <ChevronDown
          aria-hidden
          className={cn(
            "size-4 shrink-0 text-muted-foreground motion-safe:transition-transform motion-safe:duration-200",
            isExpanded && "rotate-180",
          )}
        />
      </button>
      {isExpanded && (
        <div id={panelId} className="pt-1 pb-4">
          {entry.notice === null ? (
            <p className="text-sm text-muted-foreground">이 판은 변경 안내가 없습니다.</p>
          ) : (
            <Markdown content={entry.notice} />
          )}
        </div>
      )}
    </li>
  );
}

type DisclosureToggleProps = {
  isExpanded: boolean;
  panelId: string;
  onToggle: () => void;
  children: ReactNode;
};

/** 문단 밖에 홀로 선 글자 버튼이라 보더가 없다 — 포커스는 불투명 1px 아웃라인이 3:1 을 지고 50% 링을 곁들인다. */
function DisclosureToggle({ isExpanded, panelId, onToggle, children }: DisclosureToggleProps) {
  return (
    <button
      type="button"
      aria-expanded={isExpanded}
      aria-controls={panelId}
      onClick={onToggle}
      className="-mx-2 flex min-h-9 items-center gap-1 rounded-md px-2 text-sm font-medium text-primary outline-none hover:bg-muted focus-visible:outline-1 focus-visible:outline-solid focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50 motion-safe:transition-colors"
    >
      {children}
      <ChevronDown
        aria-hidden
        className={cn("size-4 motion-safe:transition-transform motion-safe:duration-200", isExpanded && "rotate-180")}
      />
    </button>
  );
}

function LegalDocumentSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <div className="h-4 w-full animate-pulse rounded bg-muted" />
      <div className="h-4 w-full animate-pulse rounded bg-muted" />
      <div className="h-4 w-3/4 animate-pulse rounded bg-muted" />
    </div>
  );
}
