import { Link } from "@tanstack/react-router";

import { isServerUnreachable } from "@/shared/api/isServerUnreachable";
import { readLabError } from "@/shared/api/readLabError";
import { Button } from "@/shared/ui/Button";
import { Notice } from "@/shared/ui/Notice";
import { ServerUnreachableNotice } from "@/shared/ui/ServerUnreachableNotice";

type RunDetailFailureProps = {
  error: unknown;
  onRetry: () => void;
};

const BACK_TO_LIST_CLASS =
  "inline-flex h-7 items-center rounded-md bg-accent px-3 text-body font-medium text-accent-ink focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent";

/**
 * 런 상세를 받지 못했을 때. 서버에 닿지 못했으면 띄우는 방법을(목록과 같은 안내), 없는 런·열지 않는 런이면 서버 문장을 그대로
 * 보이고 목록으로 돌아갈 길을 둔다.
 */
export function RunDetailFailure({ error, onRetry }: RunDetailFailureProps) {
  if (isServerUnreachable(error)) return <ServerUnreachableNotice onRetry={onRetry} />;

  const labError = readLabError(error);
  const backToList = (
    <Link to="/" className={BACK_TO_LIST_CLASS}>
      런 목록으로
    </Link>
  );

  if (labError?.reason === "notFound") {
    return (
      <Notice title="이 런이 없다" action={backToList}>
        <p className="text-ink">{labError.detail}</p>
        <p>
          주소의 런 id 가 옛 것이거나, 측정 서버가 훑은 뒤 묶음이 옮겨졌다. 목록에서 새로 훑은 뒤 다시 연다.
        </p>
      </Notice>
    );
  }
  if (labError?.reason === "unsupported" || labError?.reason === "openFailed") {
    return (
      <Notice title="이 런은 열지 않는다" action={backToList}>
        <p className="text-ink">{labError.detail}</p>
        <p className="font-mono text-data text-ink-muted">{labError.reason}</p>
      </Notice>
    );
  }
  return (
    <Notice
      title="런을 받지 못했다"
      action={
        <div className="flex items-center gap-2">
          <Button variant="primary" onClick={onRetry}>
            다시 시도
          </Button>
          <Link to="/" className="text-body text-ink-secondary hover:text-ink">
            런 목록으로
          </Link>
        </div>
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
