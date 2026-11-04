import { Button } from "@/shared/ui/Button";
import { Notice } from "@/shared/ui/Notice";

type RunListEmptyProps = {
  refreshLabel: string;
  isRefreshing: boolean;
  onRefresh: () => void;
};

/** 런 루트에서 측정 묶음을 하나도 찾지 못했을 때 — 무엇을 두면 보이는지 적는다. */
export function RunListEmpty({ refreshLabel, isRefreshing, onRefresh }: RunListEmptyProps) {
  return (
    <Notice
      title="런 루트에서 측정 묶음을 찾지 못했다"
      action={
        <Button variant="primary" onClick={onRefresh} disabled={isRefreshing}>
          {refreshLabel}
        </Button>
      }
    >
      <p>
        측정 서버는 런 루트(기본 <span className="font-mono text-ink">apps/api/probe-runs</span>, 서버의{" "}
        <span className="font-mono text-ink">--root</span> 로 바꾼다) 아래에서 첫 줄이 드라이버 줄(meta·opening 등)인{" "}
        <span className="font-mono text-ink">.jsonl</span> 을 측정 묶음으로 읽는다.
      </p>
      <p>묶음을 둔 뒤 새로 훑는다 — 서버가 처음 훑은 뒤에 생긴 묶음은 다시 훑어야 보인다.</p>
    </Notice>
  );
}
