import { type ReactNode, useId, useState } from "react";
import type { ApiError, components } from "@ai-character-chat/api-types";
import { Markdown } from "@ai-character-chat/ui/components/markdown";
import { cn } from "@ai-character-chat/ui/lib/utils";
import type { UseQueryResult } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";

import {
  type ChangeNoticeEntry,
  LEGAL_DOCUMENT_LABEL,
  type LegalConsentKind,
  type LegalDocumentResponse,
  selectChangesSinceOldestConsent,
  toChangeNoticeEntries,
} from "@/entities/legal";
import { formatKstDate } from "@/shared/lib/time/formatKstDate";

type LegalChangesResponse = components["schemas"]["LegalChangesResponse"];

/** 모달(`popover` 면) 안 마크다운. 인라인 코드 채움은 `muted` 면 그 면과 같은 값이라 사라지므로 `secondary` 로 올리고, 제목은
 * 카드 제목(`text-sm`)보다 크지 않게 눌러 모달 제목이 화면에서 가장 큰 글자로 남게 한다. */
const MODAL_MARKDOWN_CLASSNAME = "[&_code]:bg-secondary [&_h1]:text-sm [&_h2]:text-sm";

const EMPTY_NOTICE_TEXT = "이 판은 변경 안내가 없습니다 — 전문을 확인해 주세요";

type ReconsentDocumentSectionProps = {
  kind: LegalConsentKind;
  docQuery: UseQueryResult<LegalDocumentResponse, ApiError>;
  changesQuery: UseQueryResult<LegalChangesResponse, ApiError>;
  /** 이 문서에서 다시 동의할 단위들이 각각 마지막으로 동의한 판. 가장 오래된 판 뒤의 안내를 모두 보인다. */
  consentedVersions: (string | null)[];
};

/** 다시 동의할 문서 하나 — [문서명 · 판 · 시행일] → 접힌 전문 → 마지막 동의 이후 변경 안내. 전문 토글을 문서 머리 바로
 * 아래에 두는 것은 안내가 길어도 "전문 보기"가 늘 같은 자리에 있게 하려는 것이고, 안내는 가장 최근 판만 펼쳐 둔다.
 *
 * 문서끼리는 테두리 상자가 아니라 제목과 구분선으로 가른다. 대화상자 안에 상자를 한 겹 더 두면 좁은 화면에서 긴 안내가
 * 읽히는 폭이 양쪽 32px 줄어든다. */
export function ReconsentDocumentSection({ kind, docQuery, changesQuery, consentedVersions }: ReconsentDocumentSectionProps) {
  const titleId = useId();
  const label = LEGAL_DOCUMENT_LABEL[kind];

  return (
    <section
      aria-labelledby={titleId}
      className="flex flex-col gap-4 not-first:border-t not-first:border-border not-first:pt-6"
    >
      <div className="flex flex-col gap-1">
        <h3 id={titleId} className="text-sm font-semibold text-foreground">
          {label}
        </h3>
        <DocumentMeta docQuery={docQuery} />
      </div>
      <FullText label={label} docQuery={docQuery} />
      <ChangeNotices label={label} changesQuery={changesQuery} consentedVersions={consentedVersions} />
    </section>
  );
}

function DocumentMeta({ docQuery }: { docQuery: UseQueryResult<LegalDocumentResponse, ApiError> }) {
  if (docQuery.isPending) return <div className="h-4 w-40 animate-pulse rounded bg-secondary" />;
  if (docQuery.isError) return null;
  return (
    <p className="text-xs text-muted-foreground">
      {docQuery.data.version} 판 · {formatKstDate(docQuery.data.effectiveAt)} 시행
    </p>
  );
}

type ChangeNoticesProps = {
  label: string;
  changesQuery: UseQueryResult<LegalChangesResponse, ApiError>;
  consentedVersions: (string | null)[];
};

function ChangeNotices({ label, changesQuery, consentedVersions }: ChangeNoticesProps) {
  if (changesQuery.isPending) {
    return (
      <div className="flex flex-col gap-2">
        <div className="h-4 w-full animate-pulse rounded bg-secondary" />
        <div className="h-4 w-3/4 animate-pulse rounded bg-secondary" />
      </div>
    );
  }

  if (changesQuery.isError) {
    return (
      <p className="text-sm break-keep text-destructive-text">
        변경 안내를 불러오지 못했어요. 전문을 확인해 주세요.
      </p>
    );
  }

  const entries = toChangeNoticeEntries(selectChangesSinceOldestConsent(changesQuery.data.items, consentedVersions));
  const [latest, ...earlier] = entries;
  if (latest === undefined) {
    return <p className="text-sm break-keep text-muted-foreground">{EMPTY_NOTICE_TEXT}</p>;
  }
  // 판이 하나면 그 판은 문서 머리의 판과 같아 판 표시를 되풀이하지 않는다.
  if (earlier.length === 0) {
    return <ChangeNoticeItem entry={latest} showVersion={false} />;
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs break-keep text-muted-foreground">
        마지막으로 동의하신 뒤 {entries.length}개 판이 시행됐어요.
      </p>
      <ChangeNoticeItem entry={latest} showVersion />
      <EarlierChangeNotices label={label} entries={earlier} />
    </div>
  );
}

/** 가장 최근 판보다 앞선 판들의 안내. 여러 판을 건너뛴 회원에게 판마다 긴 안내를 한꺼번에 펼치면 모달이 안내로 가득 차므로
 * 접어 두고, 펼칠 때만 그린다. */
function EarlierChangeNotices({ label, entries }: { label: string; entries: ChangeNoticeEntry[] }) {
  const panelId = useId();
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div className="flex flex-col gap-3 border-t border-border pt-3">
      <DisclosureButton isExpanded={isExpanded} panelId={panelId} onToggle={() => setIsExpanded((previous) => !previous)}>
        <span className="sr-only">{label} </span>
        {isExpanded ? "이전 변경 접기" : `이전 변경 ${entries.length}건 더 보기`}
      </DisclosureButton>
      {isExpanded && (
        <ol id={panelId} className="flex flex-col gap-4">
          {entries.map((entry) => (
            <li key={entry.version} className="not-first:border-t not-first:border-border not-first:pt-4">
              <ChangeNoticeItem entry={entry} showVersion />
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function ChangeNoticeItem({ entry, showVersion }: { entry: ChangeNoticeEntry; showVersion: boolean }) {
  return (
    <div className="flex flex-col gap-2">
      {showVersion && (
        <p className="text-xs font-medium text-muted-foreground">
          {entry.version} 판 · {entry.effectiveDate} 시행
        </p>
      )}
      {entry.notice === null ? (
        <p className="text-sm break-keep text-muted-foreground">{EMPTY_NOTICE_TEXT}</p>
      ) : (
        <Markdown content={entry.notice} className={MODAL_MARKDOWN_CLASSNAME} />
      )}
    </div>
  );
}

type FullTextProps = {
  label: string;
  docQuery: UseQueryResult<LegalDocumentResponse, ApiError>;
};

/** 전문은 펼칠 때만 그린다. 처리방침 전문은 4만 자가 넘어 `<details>` 처럼 닫힌 채로도 마운트하면 모달을 열 때마다 그만큼
 * 렌더한다. */
function FullText({ label, docQuery }: FullTextProps) {
  const panelId = useId();
  const [isExpanded, setIsExpanded] = useState(false);

  if (docQuery.isPending) return null;
  if (docQuery.isError) {
    return (
      <p className="text-sm break-keep text-destructive-text">전문을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <DisclosureButton isExpanded={isExpanded} panelId={panelId} onToggle={() => setIsExpanded((previous) => !previous)}>
        <span className="sr-only">{label} </span>
        {isExpanded ? "전문 접기" : "전문 보기"}
      </DisclosureButton>
      {isExpanded && (
        <div id={panelId} className="border-t border-border pt-3">
          <Markdown content={docQuery.data.bodyMarkdown} className={MODAL_MARKDOWN_CLASSNAME} />
        </div>
      )}
    </div>
  );
}

type DisclosureButtonProps = {
  isExpanded: boolean;
  panelId: string;
  onToggle: () => void;
  children: ReactNode;
};

function DisclosureButton({ isExpanded, panelId, onToggle, children }: DisclosureButtonProps) {
  return (
    <button
      type="button"
      aria-expanded={isExpanded}
      aria-controls={panelId}
      onClick={onToggle}
      className="-mx-2 flex min-h-9 items-center gap-1 self-start rounded-md px-2 text-sm font-medium text-primary outline-none hover:bg-secondary/50 focus-visible:outline-1 focus-visible:outline-solid focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50 motion-safe:transition-colors"
    >
      {children}
      <ChevronDown
        aria-hidden
        className={cn("size-4 motion-safe:transition-transform motion-safe:duration-200", isExpanded && "rotate-180")}
      />
    </button>
  );
}
