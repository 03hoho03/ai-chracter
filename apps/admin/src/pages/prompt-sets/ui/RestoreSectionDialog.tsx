import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { isApiError } from "@/shared/lib/api/client";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { useRestoreSectionMutation } from "../api/useRestoreSectionMutation";
import { promptSectionLabel } from "../model/channels";
import { PROMPT_LANE_LABELS, type PromptLane } from "../model/lane";
import { PROMPT_MODEL_LABELS, type PromptModel } from "../model/model";
import { ratingDriftLines } from "../model/ratingDrift";
import { ruleDetail } from "../model/semver";
import { RatingDriftNotice } from "./RatingDriftNotice";

type RestoreSectionDialogProps = {
  id: string;
  version: string | null;
  section: string;
  lane: PromptLane;
  model: PromptModel;
};

/** 확인 → (저장된 초안의 그 섹션에 게시 안 한 편집이 있으면) 덮어쓰기 확인. 덮어쓰기 안내는 서버 원문(채널 원문 이름과 API
 * 요청 방법을 담는다)이 아니라 화면이 채널 이름표로 만든다. */
type Step = { kind: "confirm" } | { kind: "overwrite" } | { kind: "drift"; lines: string[] };

const UNPUBLISHED_EDITS_RULE = "draft-channel-has-unpublished-edits";

/** 옛 게시본의 섹션 하나만 초안으로 가져온다. 게시하지 않으므로 서비스에는 바로 영향이 없지만 그 섹션의 저장된 초안 내용은
 * 사라진다 — 그래서 통째 복원과 같은 무게로 확인받는다. 저장된 초안의 그 섹션에 게시하지 않은 편집이 있으면 서버가 409 로
 * 멈추고, 같은 모달이 덮어쓰기 확인으로 바뀐다. */
export const RestoreSectionDialog = createCallable<RestoreSectionDialogProps, void>(
  ({ call, id, version, section, lane, model }) => {
    const restoreMutation = useRestoreSectionMutation(lane);
    const [step, setStep] = useState<Step>({ kind: "confirm" });
    const cancelRef = useRef<HTMLButtonElement>(null);
    const confirmRef = useRef<HTMLButtonElement>(null);
    const chainName = `${PROMPT_LANE_LABELS[lane]} · ${PROMPT_MODEL_LABELS[model]}`;
    const sectionName = promptSectionLabel(section);

    // 같은 모달 안 단계 전환이라 `autoFocus` 가 다시 걸리지 않는다 — 덮어쓰기 확인으로 바뀌면 첫 포커스를 `취소` 로 다시 둔다.
    useEffect(() => {
      if (step.kind === "overwrite") cancelRef.current?.focus();
      if (step.kind === "drift") confirmRef.current?.focus();
    }, [step.kind]);

    const handleRestore = async () => {
      try {
        const restored = await restoreMutation.mutateAsync({
          id,
          section,
          overwriteDraftChanges: step.kind === "overwrite",
        });
        toast.success(`${sectionName} 섹션을 ${chainName} 초안에 가져왔어요. 반영하려면 게시하세요.`);
        // 가져온 초안의 등급 규칙이 다른 레인과 갈렸으면 닫기 전에 한 번 보인다(가져오기는 이미 끝났다).
        const lines = ratingDriftLines(restored.ratingDrift);
        if (lines.length > 0) {
          setStep({ kind: "drift", lines });
          return;
        }
        call.end();
      } catch (error) {
        const detail = ruleDetail(error);
        if (isApiError(error) && error.status === 409 && detail?.rule === UNPUBLISHED_EDITS_RULE) {
          setStep({ kind: "overwrite" });
          return;
        }
        if (isApiError(error) && (error.status === 422 || error.status === 404)) {
          toast.error(detail?.message ?? (typeof error.detail === "string" ? error.detail : error.message));
          call.end();
          return;
        }
        toast.error("섹션 복원에 실패했어요. 잠시 후 다시 시도해주세요.");
      }
    };

    const isOverwrite = step.kind === "overwrite";
    const submitLabel = isOverwrite ? "덮어쓰기" : "가져오기";

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{isOverwrite ? "초안의 편집을 덮어쓸까요?" : `${sectionName} 섹션만 복원`}</DialogTitle>
            <DialogDescription className="break-keep">
              {isOverwrite ? (
                <>
                  초안의 {sectionName} 섹션에 게시하지 않은 편집이 있어요. 덮어쓰면 그 편집은 사라지고 v{version ?? "?"}의{" "}
                  {sectionName} 섹션으로 바뀌어요.
                </>
              ) : (
                <>
                  v{version ?? "?"}의 {sectionName} 섹션만{" "}
                  <span className="font-medium text-foreground">{chainName}</span> 초안으로 가져와요. 다른 섹션은
                  그대로이고, 게시해야 서비스에 반영돼요. 게시하면 이 섹션은 옛 판 번호로 돌아가지 않고 새 번호로
                  올라가요.
                </>
              )}
            </DialogDescription>
          </DialogHeader>

          {step.kind === "drift" ? (
            <>
              <RatingDriftNotice lines={step.lines} footer="가져오기는 끝났어요. 맞추려면 그 세트도 같이 고쳐 게시하세요." />
              <DialogFooter>
                <Button ref={confirmRef} type="button" onClick={() => call.end()}>
                  확인
                </Button>
              </DialogFooter>
            </>
          ) : (
            <DialogFooter>
              <Button ref={cancelRef} type="button" variant="outline" autoFocus onClick={() => call.end()}>
                취소
              </Button>
              <Button type="button" disabled={restoreMutation.isPending} onClick={() => void handleRestore()}>
                {restoreMutation.isPending ? "가져오는 중..." : submitLabel}
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    );
  },
);
