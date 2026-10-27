import { useSyncExternalStore } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Copy } from "lucide-react";

import { useIsOnline } from "../lib/useIsOnline";
import type { AutosaveStatusStore } from "../model/autosaveStatus";
import { saveStatusView } from "../model/saveStatusText";

type BuilderSaveStatusProps = {
  saveStatus: AutosaveStatusStore;
  /** [내용 복사]. 저장이 실패했거나 연결이 끊겼을 때만 보인다. */
  onCopy: () => void;
  className?: string;
};

/**
 * 빌더 저장 상태 글자 한 줄과, 마지막 편집이 서버에 없을 수 있을 때의 [내용 복사]. lg 이상은 상단바 제목 뒤, lg 미만은 폼 흐름 맨 위에
 * 같은 것을 하나씩 그린다(상단바에 글자를 놓을 폭이 없다).
 *
 * 저장 상태는 이 줄과 임시저장 버튼만 구독한다 — 셸이 구독하면 저장마다 셸과 미리보기가 다시 그려진다. 마지막 저장 시각은 구독하지 않고
 * 그릴 때 읽는다(저장이 끝날 때마다 상태가 "저장 중"에서 바뀌어 이 줄이 다시 그려진다).
 *
 * 보조기기 상태 영역은 두지 않는다. 입력을 멈출 때마다 "저장 중"·"저장됨"을 읽으면 소음이고, 실패는 실패 토스트가, 연결 끊김은
 * 임시저장 버튼의 상태 영역이 이미 알린다.
 */
export function BuilderSaveStatus({ saveStatus, onCopy, className }: BuilderSaveStatusProps) {
  const status = useSyncExternalStore(saveStatus.subscribe, saveStatus.getSnapshot, saveStatus.getSnapshot);
  const isOnline = useIsOnline();
  const view = saveStatusView(status, isOnline, saveStatus.getLastSavedAt());

  return (
    <div className={cn("flex min-w-0 items-center gap-2", className)}>
      <p className={cn("min-w-0 truncate text-xs", view.isFailure ? "font-medium text-destructive-text" : "text-muted-foreground")}>
        {view.text}
      </p>
      {view.offersCopy && <CopyDraftButton className="shrink-0" onClick={onCopy} />}
    </div>
  );
}

/** [내용 복사] 버튼. 상태 줄과 자동저장 실패 토스트가 같은 모양을 쓴다(토스트에서는 `ml-auto hover:bg-secondary` 를 얹는다 — 토스트 면이
 * popover 라 outline 의 hover 채움(muted)이 사라진다). 손가락 포인터에서는 40px 로 올린다. */
export function CopyDraftButton({ className, onClick }: { className?: string; onClick: () => void }) {
  return (
    <Button type="button" variant="outline" size="sm" className={cn("pointer-coarse:h-10", className)} onClick={onClick}>
      <Copy aria-hidden />
      내용 복사
    </Button>
  );
}
