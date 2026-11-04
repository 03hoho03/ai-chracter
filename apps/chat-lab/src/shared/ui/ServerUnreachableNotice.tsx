import { CHAT_LAB_API_BASE_URL } from "@/shared/api/client";
import { Button } from "@/shared/ui/Button";
import { Notice } from "@/shared/ui/Notice";

const SERVER_COMMAND = "cd apps/api && uv run python scripts/chat_lab_server.py";

/** 측정 서버에 닿지 못했을 때(응답 자체가 없음) — 서버의 거부 사유 대신 서버를 띄우는 방법을 보인다. 목록·상세가 같은 안내를 쓴다. */
export function ServerUnreachableNotice({ onRetry }: { onRetry: () => void }) {
  return (
    <Notice
      title="측정 서버에 연결하지 못했다"
      action={
        <Button variant="primary" onClick={onRetry}>
          다시 시도
        </Button>
      }
    >
      <p>측정 서버가 꺼져 있거나 다른 주소에 떠 있다. 저장소 루트에서 아래 명령으로 띄운 뒤 다시 시도한다.</p>
      <pre className="overflow-x-auto rounded-md bg-surface-sunken p-3 font-mono text-mono whitespace-pre-wrap text-ink">
        {SERVER_COMMAND}
      </pre>
      <p className="text-data">
        이 화면이 찾는 주소는 <span className="font-mono text-ink">{CHAT_LAB_API_BASE_URL}</span> 이다. 다른 포트에 띄웠다면
        <span className="font-mono"> VITE_CHAT_LAB_API</span> 로 맞춘다.
      </p>
    </Notice>
  );
}
