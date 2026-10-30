import { CHAT_LAB_API_BASE_URL } from "@/shared/api/client";
import { isServerUnreachable } from "@/shared/api/isServerUnreachable";
import { readLabError } from "@/shared/api/readLabError";
import { Button } from "@/shared/ui/Button";

import { RunListNotice } from "./RunListNotice";

const SERVER_COMMAND = "cd apps/api && uv run python scripts/chat_lab_server.py";

type RunListFailureProps = {
  error: unknown;
  onRetry: () => void;
};

/** 런 목록을 받지 못했을 때. 서버에 닿지 못했으면 띄우는 방법을, 서버가 거부했으면 그 사유를 그대로 보인다. */
export function RunListFailure({ error, onRetry }: RunListFailureProps) {
  const retry = (
    <Button variant="primary" onClick={onRetry}>
      다시 시도
    </Button>
  );

  if (isServerUnreachable(error)) {
    return (
      <RunListNotice title="측정 서버에 연결하지 못했다" action={retry}>
        <p>
          측정 서버가 꺼져 있거나 다른 주소에 떠 있다. 저장소 루트에서 아래 명령으로 띄운 뒤 다시 시도한다.
        </p>
        <pre className="overflow-x-auto rounded-md bg-surface-sunken p-3 font-mono text-mono whitespace-pre-wrap text-ink">
          {SERVER_COMMAND}
        </pre>
        <p className="text-data">
          이 화면이 찾는 주소는 <span className="font-mono text-ink">{CHAT_LAB_API_BASE_URL}</span> 이다. 다른 포트에 띄웠다면
          <span className="font-mono"> VITE_CHAT_LAB_API</span> 로 맞춘다.
        </p>
      </RunListNotice>
    );
  }

  const labError = readLabError(error);
  return (
    <RunListNotice title="런 목록을 받지 못했다" action={retry}>
      <p className="text-ink">{labError ? labError.detail : failureMessage(error)}</p>
      {labError !== undefined && <p className="font-mono text-data text-ink-muted">{labError.reason}</p>}
    </RunListNotice>
  );
}

function failureMessage(error: unknown): string {
  return error instanceof Error ? error.message : "측정 서버가 알 수 없는 모양으로 실패했다.";
}
