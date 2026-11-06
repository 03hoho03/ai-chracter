import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { useState } from "react";
import { useMutationFlow, type MutationCall } from "react-call/mutation-flow";

import { createCallable } from "@/shared/lib/callable/createCallable";
import { focusInitialElement } from "@/shared/lib/callable/focusInitialElement";

import { classifyCredentialFailure, type FailureContext } from "../model/failure";
import { CACHE_BREAK_TEXT } from "../model/messages";
import type { CandidateChange } from "../model/status";
import { CandidateChangeList } from "./CandidateChangeList";
import { FailureAlert } from "./FailureAlert";
import type { CandidateChangeOutcome } from "./screenSlots";

type ConfirmActionDialogProps = {
  title: string;
  /** 무엇이 바뀌는지. 첫 문장은 설명으로, 나머지는 본문에 둔다. */
  sentences: string[];
  changes: CandidateChange[];
  /** 바뀌는 한쪽이 env 키다(목록 사용 켜기·끄기). */
  across?: "from-env" | "to-env";
  /** 첫 후보의 계정이 바뀐다 — 진행 중인 방의 프롬프트 캐시가 한 번 끊긴다. */
  showCacheNote: boolean;
  confirmLabel: string;
  pendingLabel: string;
  /** 끄기와 받을 항목이 없어지는 동작은 경고 틴트다. */
  tone: "default" | "destructive";
  /** 확정하면 이 안에서 보낸다. 실패하면 던진다. */
  run: () => Promise<void>;
  failureContext?: FailureContext;
};

/**
 * 지금 쓰이는 항목이 바뀌는 동작의 확인(순서·켜기·끄기, 목록 사용 켜기·끄기). 바뀌는 축과 그 결과를 누르기 전에 보이고, 확정하면 이
 * 안에서 보낸다. 실패는 닫지 않고 그 안에 문구로 남긴다 — 예외는 순서 저장이 낡은 판으로 거절된 경우로, 다시 눌러도 같은 거절이라
 * 닫고 목록 화면이 순서 절 위에 안내한다.
 *
 * 보내는 동안은 Esc·바깥 누르기·닫기·취소로 닫지 않는다 — 닫은 뒤 실패하면 그 오류를 보일 자리가 없다.
 */
export const ConfirmActionDialog = createCallable<ConfirmActionDialogProps, CandidateChangeOutcome>(
  ({ call, title, sentences, changes, across, showCacheNote, confirmLabel, pendingLabel, tone, run, failureContext }) => {
    const [failureMessage, setFailureMessage] = useState<string | null>(null);
    const submit = useMutationFlow(call, async (flow: MutationCall<CandidateChangeOutcome>) => {
      setFailureMessage(null);
      try {
        await run();
        flow.end({ status: "done" });
      } catch (error) {
        const failure = classifyCredentialFailure(error, failureContext);
        if (failure.kind === "stale-order") {
          flow.end({ status: "stale", message: failure.message });
          return;
        }
        setFailureMessage(failure.message);
      }
    });

    const close = () => {
      if (!submit.pending) call.end({ status: "cancelled" });
    };
    const [lead, ...rest] = sentences;
    const hasBody = rest.length > 0 || changes.length > 0 || showCacheNote || failureMessage !== null;

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && close()}>
        <DialogContent className="sm:max-w-lg" onOpenAutoFocus={focusInitialElement}>
          <DialogHeader>
            <DialogTitle className="wrap-anywhere">{title}</DialogTitle>
            {lead !== undefined && <DialogDescription>{lead}</DialogDescription>}
          </DialogHeader>

          {hasBody && (
            <DialogBody scrollLabel="바뀌는 내용" className="flex flex-col gap-4">
              {rest.map((sentence) => (
                <p key={sentence} className="text-sm break-keep text-foreground">
                  {sentence}
                </p>
              ))}
              {changes.length > 0 && <CandidateChangeList changes={changes} across={across} />}
              {showCacheNote && <p className="text-sm break-keep text-muted-foreground">{CACHE_BREAK_TEXT}</p>}
              {failureMessage !== null && <FailureAlert message={failureMessage} />}
            </DialogBody>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              autoFocus
              data-initial-focus
              disabled={submit.pending}
              onClick={close}
            >
              취소
            </Button>
            <Button type="button" variant={tone} disabled={submit.pending} onClick={() => submit()}>
              {submit.pending ? pendingLabel : confirmLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
