import type { ReactNode } from "react";

import type { RunListItem } from "@/shared/api/client";
import { formatCount } from "@/shared/lib/formatNumber";
import { Button } from "@/shared/ui/Button";

import { relativeToFolder } from "../model/folderTree";
import { describeAttention, type AttentionTone } from "../model/runAttention";
import {
  describeGroupCost,
  describeRunCost,
  formatDateRange,
  formatLabel,
  formatStartedAt,
  MODEL_SOURCE_LABELS,
} from "../model/runFormat";
import { isOpened, type GroupSummary, type RunRow } from "../model/runRows";
import { CostText } from "./CostText";

type RunPreviewProps = {
  row: RunRow | undefined;
  folder: string;
  onOpen: (row: RunRow) => void;
};

const TONE_CLASSES = {
  danger: "text-danger",
  warn: "text-warn",
  quiet: "text-ink-secondary",
} as const satisfies Record<AttentionTone, string>;

/** 오른쪽 미리보기 — 고른 행을 목록 응답의 칸만으로 그린다(런 상세를 따로 부르지 않는다). */
export function RunPreview({ row, folder, onOpen }: RunPreviewProps) {
  if (!row) {
    return (
      <PreviewFrame action={null}>
        <p className="text-ink-muted">고른 행이 없다.</p>
      </PreviewFrame>
    );
  }
  if (row.kind === "group") {
    return (
      <PreviewFrame
        action={
          <Button variant="primary" onClick={() => onOpen(row)}>
            폴더 보기 <span aria-hidden="true">↵</span>
          </Button>
        }
      >
        <GroupDetails folder={relativeToFolder(row.folder, folder)} fullPath={row.folder} summary={row.summary} />
      </PreviewFrame>
    );
  }
  return (
    <PreviewFrame
      action={
        <Button variant="primary" onClick={() => onOpen(row)}>
          열기 <span aria-hidden="true">↵</span>
        </Button>
      }
    >
      <RunDetails item={row.item} />
    </PreviewFrame>
  );
}

function PreviewFrame({ action, children }: { action: ReactNode; children: ReactNode }) {
  return (
    <>
      <div className="sticky top-0 z-10 flex h-8 items-center gap-2 border-b border-border bg-surface pr-1 pl-3">
        <h2 className="text-section text-ink">미리보기</h2>
        <span className="ml-auto">{action}</span>
      </div>
      <div className="space-y-4 p-3">{children}</div>
    </>
  );
}

function RunDetails({ item }: { item: RunListItem }) {
  const opened = isOpened(item);
  const attention = describeAttention(item);

  return (
    <>
      <div>
        <h3 className="text-title text-balance text-ink">{item.storyName ?? "이야기 이름 없음"}</h3>
        <p className="mt-0.5 font-mono text-label break-all text-ink-muted">{item.path}</p>
      </div>
      <section aria-label="먼저 볼 것">
        <h4 className="text-section text-ink">먼저 볼 것</h4>
        <ul className="mt-1.5 space-y-1 text-data">
          {attention.map((line) => (
            <li key={line.text} className={TONE_CLASSES[line.tone]}>
              {line.text}
            </li>
          ))}
        </ul>
      </section>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-data">
        {opened && (
          <>
            <Field label="턴">{item.turnCount}</Field>
            <Field label="시작">{formatStartedAt(item.startedAt) ?? <Missing />}</Field>
            <Field label="끝">{formatStartedAt(item.endedAt) ?? <Missing />}</Field>
            <Field label="원가">
              <CostText cost={describeRunCost(item)} hasNote />
            </Field>
            <Field label="불일치">{formatCount(item.mismatchCount ?? 0)}</Field>
            <Field label="주의">{formatCount(item.cautionCount ?? 0)}</Field>
            <Field label="보낸 모델">
              <ModelList models={item.sentChatModels} />
              {item.sentChatModelsFrom != null && (
                <span className="block text-ink-muted">{MODEL_SOURCE_LABELS[item.sentChatModelsFrom]}</span>
              )}
            </Field>
            <Field label="설정값">
              <span title="방 스냅숏의 effectiveChatModel — 방 설정에서 서버가 쓰겠다고 한 값이라, 모델을 바꿔 돌린 런에서는 보낸 모델과 다르다">
                <ModelList models={item.configuredChatModels} />
              </span>
            </Field>
          </>
        )}
        <Field label="형식">{formatLabel(item.format)}</Field>
        <Field label="짝 파일">
          {[
            `스냅숏 ${item.hasSnapshots ? "있음" : "없음"}`,
            `덤프 ${item.hasDump ? "있음" : "없음"}`,
            `턴 기록 ${item.hasChatTurns ? "있음" : "없음"}`,
          ].join(" · ")}
        </Field>
        <Field label="방 id">
          <span className="font-mono break-all">{item.roomId}</span>
        </Field>
      </dl>
    </>
  );
}

function GroupDetails({ folder, fullPath, summary }: { folder: string; fullPath: string; summary: GroupSummary }) {
  return (
    <>
      <div>
        <h3 className="font-mono text-title break-all text-ink">{folder}</h3>
        <p className="mt-0.5 font-mono text-label break-all text-ink-muted">{fullPath}</p>
      </div>
      <p className="text-data text-ink-secondary">
        대량 시도 폴더라 표에서 한 줄로 접었다. 들어가면 런마다 행이 놓인다.
      </p>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-data">
        <Field label="런">{formatCount(summary.runCount)}개</Field>
        <Field label="시작">{formatDateRange(summary.earliestStartedAt, summary.latestStartedAt) ?? <Missing />}</Field>
        <Field label="원가 합">
          <CostText cost={describeGroupCost(summary)} hasNote />
        </Field>
        <Field label="불일치 합">
          <span className={summary.mismatchTotal > 0 ? "text-warn" : undefined}>{formatCount(summary.mismatchTotal)}</span>
        </Field>
        <Field label="주의 합">
          <span className={summary.cautionTotal > 0 ? "text-warn" : undefined}>{formatCount(summary.cautionTotal)}</span>
        </Field>
        {summary.needsExportCount > 0 && <Field label="내보내기 필요">{formatCount(summary.needsExportCount)}개</Field>}
        {summary.oldFormatCount > 0 && <Field label="이전 형식(원가 없음)">{formatCount(summary.oldFormatCount)}개</Field>}
        {summary.unopenedCount > 0 && (
          <Field label="열 수 없음">
            <span className="text-danger">{formatCount(summary.unopenedCount)}개</span>
          </Field>
        )}
      </dl>
    </>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-ink-muted">{label}</dt>
      <dd className="min-w-0 tabular-nums text-ink">{children}</dd>
    </>
  );
}

function ModelList({ models }: { models: string[] | undefined }) {
  if (!models || models.length === 0) return <Missing />;
  return <span className="font-mono break-all">{models.join(", ")}</span>;
}

/** 값이 있어야 할 자리에 기록이 없다는 것을 말한다 — 대시로 덮지 않는다. */
function Missing() {
  return <span className="text-ink-muted">기록 없음</span>;
}
