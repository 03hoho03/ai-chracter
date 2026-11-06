import { Button } from "@ai-character-chat/ui/components/button";

import type { CandidateChange } from "../model/status";
import { CandidateChangeList } from "./CandidateChangeList";

type CheckDroppedNoticeProps = {
  changes: readonly CandidateChange[];
};

/** 확인 호출로 이 항목이 첫 후보에서 빠진 축. 확정 실패(모델 접근·크레딧 등)만 빠진다 — 일시 오류는 런타임이 이전 결과로 내려가
 * 그대로 받는다. 알림은 잠깐 떠 있다 사라지지만 이 결과는 운영자가 다음 할 일(다음 항목 확인·충전)을 고르는 근거라 블록에 남긴다. */
export function CheckDroppedNotice({ changes }: CheckDroppedNoticeProps) {
  return (
    <div role="status" className="flex flex-col gap-1">
      <p className="text-sm break-keep text-foreground">확정 실패한 모델은 다음 호출부터 이 항목으로 보내지 않아요.</p>
      <CandidateChangeList changes={changes} />
    </div>
  );
}

type CheckFailureNoticeProps = {
  message: string;
  /** 행 버튼 접근 이름의 앞머리("2번째 운영 계정"). */
  itemName: string;
  /** 저장한 키를 읽을 수 없을 때만 — 같은 키를 다시 붙여넣으면 암호문을 다시 써 살아난다. */
  onRepasteSecret?: () => void;
};

/** 확인 호출이 거절된 이유. 항목의 키 교체 버튼과 접근 이름이 겹치지 않게 다시 붙여넣기 버튼은 그 일을 이름으로 쓴다. */
export function CheckFailureNotice({ message, itemName, onRepasteSecret }: CheckFailureNoticeProps) {
  return (
    <div className="flex flex-col items-start gap-2">
      <p role="alert" className="text-sm break-keep text-destructive-text">
        {message}
      </p>
      {onRepasteSecret !== undefined && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-label={`${itemName} 같은 키 다시 붙여넣기`}
          onClick={onRepasteSecret}
        >
          같은 키 다시 붙여넣기…
        </Button>
      )}
    </div>
  );
}
