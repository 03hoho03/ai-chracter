import { isServerUnreachable } from "@/shared/api/isServerUnreachable";
import { readLabError } from "@/shared/api/readLabError";
import { Button } from "@/shared/ui/Button";
import { Notice } from "@/shared/ui/Notice";
import { ServerUnreachableNotice } from "@/shared/ui/ServerUnreachableNotice";

type RunListFailureProps = {
  error: unknown;
  onRetry: () => void;
};

/** 런 목록을 받지 못했을 때. 서버에 닿지 못했으면 띄우는 방법을, 서버가 거부했으면 그 사유를 그대로 보인다. */
export function RunListFailure({ error, onRetry }: RunListFailureProps) {
  if (isServerUnreachable(error)) return <ServerUnreachableNotice onRetry={onRetry} />;

  const labError = readLabError(error);
  return (
    <Notice
      title="런 목록을 받지 못했다"
      action={
        <Button variant="primary" onClick={onRetry}>
          다시 시도
        </Button>
      }
    >
      <p className="text-ink">{labError ? labError.detail : failureMessage(error)}</p>
      {labError !== undefined && <p className="font-mono text-data text-ink-muted">{labError.reason}</p>}
    </Notice>
  );
}

function failureMessage(error: unknown): string {
  return error instanceof Error ? error.message : "측정 서버가 알 수 없는 모양으로 실패했다.";
}
