import { useEffect, useRef, useState } from "react";

import type { ForgetOutcome } from "../model/forgetOutcome";
import type { MemoryListNotice } from "./MemoryItemsParts";

/** 잊게 하기 확인 대화의 결과를 목록 위 알림으로 옮기고, 알림이 바뀔 때마다 포커스를 그리로 보낸다 — 잊은 행과 그 행의
 * 지우개 버튼이 함께 사라져 대화 상자가 닫힌 뒤 포커스가 `<body>`로 떨어지기 때문이다. 취소는 아무것도 바꾸지 않는다(포커스는
 * 대화 상자를 연 버튼으로 돌아간다). */
export function useForgetResultNotice() {
  const [notice, setNotice] = useState<MemoryListNotice | undefined>(undefined);
  const noticeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (notice) noticeRef.current?.focus();
  }, [notice]);

  function showOutcome(outcome: ForgetOutcome, label: string) {
    if (outcome.kind === "forgotten") {
      setNotice({ kind: "forgotten", label, linkedEpisodeCount: outcome.linkedEpisodeCount });
    } else if (outcome.kind === "notice") {
      setNotice({ kind: "message", message: outcome.message });
    }
  }

  return { notice, noticeRef, showOutcome };
}
