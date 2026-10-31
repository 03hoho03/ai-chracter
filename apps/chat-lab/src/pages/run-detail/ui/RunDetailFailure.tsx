import { Link } from "@tanstack/react-router";

import { isServerUnreachable } from "@/shared/api/isServerUnreachable";
import { readLabError } from "@/shared/api/readLabError";
import { StaticBundleError } from "@/shared/api/staticBundle";
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
 * 보이고 목록으로 돌아갈 길을 둔다. 정적 HTML 로 연 화면이면 따로 — 다시 읽어도 같고 목록도 없다.
 */
export function RunDetailFailure({ error, onRetry }: RunDetailFailureProps) {
  if (error instanceof StaticBundleError) return <StaticFailure error={error} />;
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

const STATIC_FAILURE_TITLE = {
  broken: "이 파일의 런 데이터를 읽지 못했다",
  notFound: "이 파일에 없는 런이다",
  serverless: "측정 서버가 있어야 하는 화면이다",
} as const satisfies Record<StaticBundleError["reason"], string>;

/**
 * 정적 HTML 로 연 화면의 실패. 파일은 다시 읽어도 같아 "다시 시도"를 두지 않는다. 주소가 이 파일의 런을 가리키지 않으면 그 런으로
 * 가는 길만 둔다(첫 화면이 이 파일의 런이다). 읽지 못한 파일은 다시 내보내는 것밖에 없다.
 */
function StaticFailure({ error }: { error: StaticBundleError }) {
  return (
    <Notice
      title={STATIC_FAILURE_TITLE[error.reason]}
      action={
        error.reason === "broken" ? undefined : (
          <Link to="/" className={BACK_TO_LIST_CLASS}>
            이 파일의 런 열기
          </Link>
        )
      }
    >
      <p className="text-ink">{error.message}</p>
      {error.reason === "broken" && <p>내보내기 스크립트로 이 런을 다시 내보낸다.</p>}
    </Notice>
  );
}

function failureMessage(error: unknown): string {
  return error instanceof Error ? error.message : "측정 서버가 알 수 없는 모양으로 실패했다.";
}
