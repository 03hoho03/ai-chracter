import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { isApiError } from "@/shared/lib/api/client";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { usePublishMutation } from "../api/usePublishMutation";
import { PROMPT_LANE_LABELS, type PromptLane } from "../model/lane";
import { PROMPT_MODEL_LABELS, type PromptModel } from "../model/model";

type PublishFormValues = {
  note: string;
};

type PublishPromptSetDialogProps = {
  lane: PromptLane;
  model: PromptModel;
};

// 레인화로 "다음 채팅 턴부터"가 거짓이 되는 레인이 있다.
// `publish_filter`는 채팅 턴이 아니라 제작자가 발행 버튼을 누를 때(다음 발행 심사부터) 읽힌다.
// 소설 문안은 소설 레인으로 옮겨, 채팅 레인 게시가 소설에 닿는 것은 원문 줄의 화자 라벨과 등급 규칙뿐이다(소설 호출이
// 그 둘은 원작 종류의 채팅 Gemini 세트에서 읽는다). 소설 레인 Gemini 세트는 경계 제안·문단 수정과 Gemini 로 쓰는 화
// 생성에 읽힌다.
const PUBLISH_EFFECT_COPY: Record<PromptLane, string> = {
  story: "다음 채팅 턴부터 전 서비스에 즉시 반영되고(화자 라벨과 등급 규칙은 다음 소설 작업에도 쓰여요)",
  character: "다음 채팅 턴부터 전 서비스에 즉시 반영되고(화자 라벨과 등급 규칙은 다음 소설 작업에도 쓰여요)",
  publish_filter: "다음 발행 심사부터 즉시 반영되고",
  novel: "다음 소설 경계 제안·문단 수정과 Gemini 로 쓰는 다음 화 생성부터 즉시 반영되고",
  novel_screen: "다음 노벨 공개 심사부터 즉시 반영되고",
};

/** Claude 세트는 레인마다 읽히는 자리가 하나뿐이라 문구가 레인을 따른다. 채팅 레인은 그 모델을 고른 방의 응답 생성에만
 * 읽히고(판정·요약은 Gemini 세트), 소설 레인은 그 모델로 쓰는 화 생성에만 읽힌다(경계 제안·문단 수정은 Gemini 세트).
 * 상위 모델이 꺼져 있거나 허용이 없으면 그 자리도 Gemini 로 돌아 게시해도 아무 데도 쓰이지 않는다. */
function toClaudePublishEffectCopy(lane: PromptLane): string {
  if (lane === "novel") {
    return "이 모델로 쓰는 다음 소설 화 생성부터 즉시 반영되고(상위 모델이 꺼져 있거나 허용이 없으면 쓰이지 않아요)";
  }
  return "이 모델을 고른 방의 다음 채팅 턴 응답 생성부터 즉시 반영되고(상위 모델이 꺼져 있으면 쓰이지 않아요)";
}

/** 게시는 전 서비스 채팅에 즉시 반영되는 되돌리기 어려운 행동이라 다이얼로그로 한 번
 * 더 확인받는다 — legal의 `PublishDialog`와 같은 어휘(react-call, 자체 호출형). 버전은
 * 서버가 자동 증가로 부여하므로 입력받지 않고 `note`만 받는다.
 *
 * 게시 검증 규칙 위반(422)은 이 다이얼로그의 어느 입력값과도 무관한 구조적 문제라 필드 에러로
 * 붙이지 않는다 — 닫고 토스트로 알려 어드민이 어느 섹션을 고쳐야 하는지 보게 한다. */
export const PublishPromptSetDialog = createCallable<PublishPromptSetDialogProps, void>(({ call, lane, model }) => {
  const publishMutation = usePublishMutation(lane, model);
  const chainName = `${PROMPT_LANE_LABELS[lane]} · ${PROMPT_MODEL_LABELS[model]}`;
  const {
    register,
    handleSubmit,
    formState: { isSubmitting },
  } = useForm<PublishFormValues>({ defaultValues: { note: "" } });

  const onSubmit = async (values: PublishFormValues) => {
    try {
      const published = await publishMutation.mutateAsync({ note: values.note });
      // 버전은 레인·모델과 무관하게 전역 단조라 이 체인의 직전 버전과 번호가 안 이어질 수
      // 있다(예: story v3 다음이 v5).
      toast.success(
        `${chainName} v${published.version}을(를) 게시했어요. 버전 번호는 레인·모델과 무관하게 전역으로 매겨져요.`,
      );
      call.end();
    } catch (error) {
      if (isApiError(error) && error.status === 422 && typeof error.detail === "object" && error.detail) {
        const rule = "rule" in error.detail ? String(error.detail.rule) : "검증 실패";
        const message = "message" in error.detail ? String(error.detail.message) : error.message;
        toast.error(`${rule}: ${message}`);
      } else {
        toast.error("게시에 실패했어요. 잠시 후 다시 시도해주세요.");
      }
      call.end();
    }
  };

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>프롬프트 세트 게시</DialogTitle>
          <DialogDescription className="break-keep">
            지금 저장된 <span className="font-medium text-foreground">{chainName}</span> 초안을 새 버전으로
            게시해요. {model === "gemini" ? PUBLISH_EFFECT_COPY[lane] : toClaudePublishEffectCopy(lane)}, 초안은 게시
            후에도 그대로 남아요.
          </DialogDescription>
        </DialogHeader>

        <form
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void handleSubmit(onSubmit)(event);
          }}
          className="flex flex-col gap-3"
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="prompt-publish-note">메모</Label>
            <Textarea
              id="prompt-publish-note"
              placeholder="왜 바꿨는지 남겨두면 나중에 롤백할 때 도움이 돼요."
              {...register("note")}
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" autoFocus onClick={() => call.end()}>
              취소
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "게시 중..." : "게시"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
});
