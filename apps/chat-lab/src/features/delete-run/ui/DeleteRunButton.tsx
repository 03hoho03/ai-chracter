import { useEffect, useId, useRef, type SyntheticEvent } from "react";

import { RawBadge } from "@/entities/run-version";
import { describeHostedFailure } from "@/shared/api/service/hostedFailure";
import type { HostedVersion } from "@/shared/api/service/serviceClient";
import { assertNever } from "@/shared/lib/assertNever";
import { formatCount } from "@/shared/lib/formatNumber";
import { useElapsedSeconds } from "@/shared/lib/useElapsedSeconds";
import { Button } from "@/shared/ui/Button";

import type { DeleteOutcome } from "../api/deleteRunIfUnchanged";
import { useDeleteRun } from "../api/useDeleteRun";
import { deleteCopy, deleteFailureText, versionsChangedText, type DeleteSubject } from "../model/deleteCopy";

type DeleteRunButtonProps = {
  runId: string;
  latest: HostedVersion;
  versionCount: number;
  storyName?: string | null;
  path?: string;
  /** 여는 버튼의 낱말 — 자리마다 다르다(미리보기 "런 지우기…", 상세 머리 "지우기", 읽지 못하는 런 띠 "지우기…"). */
  triggerLabel: string;
  /** 지운 뒤(이미 지워졌어도). 상세 머리는 지운 런을 떠나 목록으로 옮긴다. */
  onDeleted?: (outcome: DeleteOutcome) => void;
};

/**
 * 런 지우기 — 여는 버튼(Ghost)과 모달 확인 대화. 대화는 네이티브 `<dialog>` 라 포커스 가둠·뒤 화면 막기·Esc 닫기를 브라우저가
 * 맡는다. 지우기는 그 런의 모든 판을 되돌릴 수 없게 지우므로, 판 수를 제목과 위험 버튼 둘 다에 적고 처음 포커스는 취소에 둔다.
 */
export function DeleteRunButton({ runId, latest, versionCount, storyName, path, triggerLabel, onDeleted }: DeleteRunButtonProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const deletion = useDeleteRun(runId, (outcome) => {
    dialogRef.current?.close();
    onDeleted?.(outcome);
  });
  const seconds = useElapsedSeconds(deletion.isPending);
  const copy = deleteCopy({ versionCount, runId, storyName, path });
  // 지우기가 끝났는데 대화가 남는 결과 — 그 사이 새 판이 올라왔거나 실패했다(지웠거나 이미 지워졌으면 대화가 닫힌다).
  const isAwaitingRetry = !deletion.isPending && (deletion.isError || deletion.data?.kind === "changed");

  // 지우는 동안 두 버튼이 꺼져 포커스가 body 로 떨어진다. 대화가 남는 결과가 그려진 뒤 포커스를 취소로 돌려 놓는다 — 처음 포커스와
  // 같은 자리라 엔터 한 번이 다시 지우기로 가지 않는다. 버튼이 다시 켜진 뒤여야 포커스가 들어가므로 그린 다음에 옮긴다.
  useEffect(() => {
    if (isAwaitingRetry) cancelRef.current?.focus();
  }, [isAwaitingRetry]);

  function handleOpen() {
    // 앞서 실패한 지우기의 문장이 새로 연 대화에 남지 않게 한다.
    deletion.reset();
    dialogRef.current?.showModal();
    // 엔터 한 번이 지우기로 가지 않게 처음 포커스는 취소에 둔다.
    cancelRef.current?.focus();
  }

  function handleCancel(event: SyntheticEvent<HTMLDialogElement>) {
    // 지우는 중에는 Esc 로 닫지 않는다 — 닫아도 지우기는 서비스에서 끝나, 결과를 보지 못한 채 대화만 사라진다.
    if (deletion.isPending) event.preventDefault();
  }

  function handleClose() {
    dialogRef.current?.close();
  }

  function handleConfirm() {
    // 대화가 지금 보이는 판을 넘긴다 — 지우기 직전에 서비스의 지금 판과 견주어, 그 사이 새 판이 올라왔으면 지우지 않는다.
    deletion.mutate({ sha256: latest.sha256, versionCount, raw: latest.raw });
  }

  return (
    <>
      <Button onClick={handleOpen}>{triggerLabel}</Button>
      <dialog
        ref={dialogRef}
        aria-labelledby={titleId}
        onCancel={handleCancel}
        className="m-auto w-lg rounded-lg bg-surface p-5 text-left text-body whitespace-normal text-ink shadow-overlay backdrop:bg-scrim"
      >
        <h2 id={titleId} className="text-title text-balance text-ink">
          {copy.title}
        </h2>
        <p className="mt-3 text-ink-secondary">
          <SubjectText subject={copy.subject} /> 런의 {copy.scope}
        </p>
        <dl className="mt-3 grid grid-cols-fields gap-x-3 gap-y-1.5 rounded-md bg-surface-raised px-3 py-2 text-data">
          <dt className="text-ink-muted">런 id</dt>
          <dd className="min-w-0 font-mono break-all text-ink">{runId}</dd>
          {path !== undefined && (
            <>
              <dt className="text-ink-muted">경로</dt>
              <dd className="min-w-0 font-mono break-all text-ink">{path}</dd>
            </>
          )}
          <dt className="text-ink-muted">판</dt>
          <dd className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-ink tabular-nums">
            {formatCount(versionCount)}개 · 최신 판 {latest.versionNumber}
            {latest.raw && <RawBadge />}
          </dd>
        </dl>
        <p className="mt-3 text-ink-secondary">
          지운 런은 목록에서 빠지고 팀 누구도 열 수 없다. 서비스에는 백업이 없다 — 되살리려면 원본 런 폴더와 그 런을 돈 로컬 DB 가 있는
          컴퓨터에서 다시 올린다.
        </p>
        {deletion.data?.kind === "changed" && (
          <p role="alert" className="mt-3 text-data text-warn">
            {versionsChangedText(deletion.data.versionCount)}
          </p>
        )}
        {deletion.isError && (
          <p role="alert" className="mt-3 text-data text-danger">
            {deleteFailureText(describeHostedFailure(deletion.error, "delete"))}
          </p>
        )}
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <Button ref={cancelRef} onClick={handleClose} disabled={deletion.isPending}>
            취소
          </Button>
          <Button variant="danger" onClick={handleConfirm} disabled={deletion.isPending} className="tabular-nums">
            {deletion.isPending ? `지우는 중 ${seconds}초` : copy.confirmLabel}
          </Button>
        </div>
      </dialog>
    </>
  );
}

/** 대화가 런을 가리키는 말 — 이야기 이름은 낫표 안에, 기계가 만든 경로·런 id 는 고정폭으로. */
function SubjectText({ subject }: { subject: DeleteSubject }) {
  switch (subject.kind) {
    case "story":
      return <span className="text-ink">「{subject.name}」</span>;
    case "path":
      return <span className="font-mono text-data break-all text-ink">{subject.path}</span>;
    case "runId":
      return <span className="font-mono text-data break-all text-ink">{subject.runId}</span>;
    default:
      return assertNever(subject);
  }
}
