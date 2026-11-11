import { Button } from "@/shared/ui/Button";
import { Notice } from "@/shared/ui/Notice";

type HostedRunListEmptyProps = {
  isReloading: boolean;
  onReload: () => void;
};

/** 서비스에 올라온 런이 하나도 없을 때 — 런이 어떻게 여기 놓이는지 적는다. 다시 받기가 이 화면의 유일한 행동이라 Primary 다. */
export function HostedRunListEmpty({ isReloading, onReload }: HostedRunListEmptyProps) {
  return (
    <Notice
      title="서비스에 올라온 런이 없다"
      action={
        <Button variant="primary" onClick={onReload} disabled={isReloading}>
          다시 받기
        </Button>
      }
    >
      <p>
        운영자가 자기 컴퓨터의 측정 서버에서 런을 올리면 여기에 놓인다. 올리는 명령은{" "}
        <span className="font-mono text-ink">apps/chat-lab/README.md</span> 의 「올리기」 절에 있다.
      </p>
    </Notice>
  );
}
