import { useNavigate } from "@tanstack/react-router";

import { RawBadge, uploadedAtText } from "@/entities/run-version";
import { DeleteRunButton } from "@/features/delete-run";
import type { RunDetail } from "@/shared/api/client";
import { formatCount } from "@/shared/lib/formatNumber";

import { useHostedRunVersion } from "../api/useHostedRunVersion";

type HostedRunActionProps = {
  runId: string;
  detail: RunDetail;
};

/**
 * 호스팅 화면의 머리 행동 자리 — 원문 표지 · 판 · 지우기. 측정 서버가 있어야 하는 턴 기록 내보내기 자리에 선다. 빵부스러기가 아니라
 * 이 자리(줄지 않는다)에 두어 긴 이야기 이름에 잘리지 않는다. 좁은 화면(640px 미만)에서는 "판 N" 낱말만 숨기고 표지와 지우기는 남긴다.
 */
export function HostedRunAction({ runId, detail }: HostedRunActionProps) {
  const navigate = useNavigate();
  const version = useHostedRunVersion(runId);
  if (version === undefined) return null;
  const { latest, versionCount } = version;

  function handleDeleted() {
    // 지운 런의 상세에 남지 않는다 — 뒤로 가기로 돌아와도 없는 런이라, 이 자리를 목록으로 바꾼다.
    void navigate({ to: "/", search: detail.run.group != null ? { folder: detail.run.group } : {}, replace: true });
  }

  return (
    <>
      {latest.raw && <RawBadge />}
      <span
        title={`살아 있는 판 ${formatCount(versionCount)}개 가운데 최신 · ${uploadedAtText(latest)}`}
        className="hidden px-1 text-data text-ink-muted tabular-nums sm:inline"
      >
        판 {latest.versionNumber}
      </span>
      <DeleteRunButton
        runId={runId}
        latest={latest}
        versionCount={versionCount}
        storyName={detail.run.storyName}
        path={detail.run.path}
        triggerLabel="지우기"
        onDeleted={handleDeleted}
      />
    </>
  );
}
