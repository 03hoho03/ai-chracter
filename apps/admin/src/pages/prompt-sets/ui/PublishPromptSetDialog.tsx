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
import { createCallable } from "react-call";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { isApiError } from "@/shared/lib/api/client";

import { usePublishMutation } from "../api/usePublishMutation";
import type { PromptLane } from "../model/lane";

type PublishFormValues = {
  note: string;
};

type PublishPromptSetDialogProps = {
  lane: PromptLane;
};

// 레인화로 "다음 채팅 턴부터"가 거짓이 되는 레인이 있다.
// `publish_filter`는 채팅 턴이 아니라 제작자가 발행 버튼을 누를 때(다음 발행 심사부터) 읽힌다.
const PUBLISH_EFFECT_COPY: Record<PromptLane, string> = {
  story: "다음 채팅 턴부터 전 서비스에 즉시 반영되고",
  character: "다음 채팅 턴부터 전 서비스에 즉시 반영되고",
  publish_filter: "다음 발행 심사부터 즉시 반영되고",
};

/** 게시는 전 서비스 채팅에 즉시 반영되는 되돌리기 어려운 행동이라 다이얼로그로 한 번
 * 더 확인받는다 — legal의 `PublishDialog`와 같은 어휘(react-call, 자체 호출형). 버전은
 * 서버가 자동 증가로 부여하므로 입력받지 않고 `note`만 받는다.
 *
 * 게시 검증 규칙 위반(422)은 이 다이얼로그의 어느 입력값과도 무관한 구조적 문제라 필드 에러로
 * 붙이지 않는다 — 닫고 토스트로 알려 어드민이 어느 섹션을 고쳐야 하는지 보게 한다. */
export const PublishPromptSetDialog = createCallable<PublishPromptSetDialogProps, void>(({ call, lane }) => {
  const publishMutation = usePublishMutation(lane);
  const {
    register,
    handleSubmit,
    formState: { isSubmitting },
  } = useForm<PublishFormValues>({ defaultValues: { note: "" } });

  const onSubmit = async (values: PublishFormValues) => {
    try {
      const published = await publishMutation.mutateAsync({ note: values.note });
      // 버전은 레인과 무관하게 전역 단조라 이 레인의 직전 버전과 번호가 안 이어질 수
      // 있다(예: story v3 다음이 v5).
      toast.success(`v${published.version}을(를) 게시했어요. 버전 번호는 레인과 무관하게 전역으로 매겨져요.`);
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
            지금 저장된 초안을 새 버전으로 게시해요. {PUBLISH_EFFECT_COPY[lane]}, 초안은 게시
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
            <Button type="button" variant="outline" onClick={() => call.end()}>
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
