import { useState } from "react";

import { RawBadge, uploadedAtText } from "@/entities/run-version";
import { DeleteRunButton } from "@/features/delete-run";
import { CONTRACT_VERSION, type UnreadableRun } from "@/shared/api/service/hostedRuns";
import { assertNever } from "@/shared/lib/assertNever";
import { formatCount } from "@/shared/lib/formatNumber";

/**
 * 이 웹이 읽지 못하는 런 띠 — 런 표 칸 맨 위에 접힌 한 줄로 서고, 펼치면 런마다 런 id·올린 때·원문 표지·까닭과 지우기. 표에서 빼되
 * 숨기지는 않는다 — 열 수는 없어도 지울 수 있어야 하고, 서비스에 무엇이 있는지 감추지 않는다.
 */
export function UnreadableRuns({ runs }: { runs: ReadonlyArray<UnreadableRun> }) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <section aria-label="이 웹이 읽지 못하는 런" className="border-b border-border">
      <button
        type="button"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((previous) => !previous)}
        className="flex h-7 w-full items-center gap-1.5 px-3 text-left text-data hover:bg-surface-raised focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent motion-safe:transition-colors"
      >
        <span aria-hidden="true" className="text-ink-muted">
          {isOpen ? "▾" : "▸"}
        </span>
        <span className="truncate text-danger">이 웹이 읽지 못하는 런 {formatCount(runs.length)}개</span>
      </button>
      {isOpen && (
        <ul className="border-t border-border">
          {runs.map((run) => (
            <li key={run.runId} className="flex items-center gap-2 border-b border-border px-3 py-1.5 last:border-b-0">
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-1.5">
                  <span title={run.runId} className="min-w-0 truncate font-mono text-data text-ink">
                    {run.runId}
                  </span>
                  {run.latest.raw && <RawBadge isCompact />}
                </div>
                <p className="truncate text-data text-ink-secondary" title={unreadableText(run)}>
                  <span className="tabular-nums">{uploadedAtText(run.latest)}</span> · {unreadableText(run)}
                </p>
              </div>
              <DeleteRunButton
                runId={run.runId}
                latest={run.latest}
                versionCount={run.versionCount}
                storyName={run.storyName}
                path={run.path}
                triggerLabel="지우기…"
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** 왜 읽지 못하는가. 계약 판이면 두 판을 함께 적는다 — 어느 쪽이 새것인지에 따라 고칠 쪽이 다르다. */
function unreadableText(run: UnreadableRun): string {
  switch (run.reason) {
    case "contract":
      return `계약 판 ${run.latest.contractVersion} — 이 웹은 ${CONTRACT_VERSION} 을 읽는다`;
    case "shape":
      return "목록 칸이 이 웹이 아는 꼴이 아니다";
    default:
      return assertNever(run.reason);
  }
}
