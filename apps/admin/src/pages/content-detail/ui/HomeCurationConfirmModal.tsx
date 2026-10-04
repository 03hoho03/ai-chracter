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

import { CONTENT_TYPE_LABELS, useHomeCurationMutation, type ContentTypeFilter } from "@/entities/admin-content";
import { isApiError } from "@/shared/lib/api/client";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { focusInitialElement } from "@/shared/lib/callable/focusInitialElement";

/** 지정 거부 code 는 OpenAPI 에 노출되지 않아 생성 타입이 없다 — 구조화 dict `detail` 을 직접 읽는다. */
const REJECTION_MESSAGES: Record<string, string> = {
  NOT_PUBLICLY_LISTED: "지금 공개 목록에 없는 작품이라 지정할 수 없어요. 공개 상태인지 확인해주세요.",
  CONTENT_TYPE_MISMATCH: "작품 유형이 맞지 않아 지정할 수 없어요.",
};

const ERROR_MESSAGE = "처리에 실패했어요. 잠시 후 다시 시도해주세요.";

/** 코멘트만 받고 검증이 없어 zod 스키마 없이 폼 값 타입만 둔다. */
type HomeCurationFormValues = {
  adminComment: string;
};

type HomeCurationConfirmModalProps = {
  contentType: ContentTypeFilter;
  contentName: string;
  /** 지정·해제가 성공해 모달이 닫힌 뒤 부른다 — 상세 레이아웃이 하단 시트를 닫는다. 거부(공개 목록에 없음 등)는 바뀐 것이 없어 부르지 않는다. */
  onSuccess?: () => void;
} & ({ mode: "set"; contentId: string; replacingName: string | null } | { mode: "clear" });

/** 홈 큐레이션 지정·해제 확인. 지정은 운영 홈 첫 화면에 바로 보이는 조작이고, 같은 유형의 기존 지정작을 밀어내므로
 * 그 이름을 보여 준다. 코멘트는 선택이다(작가에게 불이익이 없고 되돌릴 수 있다). */
export const HomeCurationConfirmModal = createCallable<HomeCurationConfirmModalProps, void>(({ call, ...props }) => {
  const curationMutation = useHomeCurationMutation(props.contentType);
  const {
    register,
    handleSubmit,
    formState: { isSubmitting },
  } = useForm<HomeCurationFormValues>({ defaultValues: { adminComment: "" } });

  const typeLabel = CONTENT_TYPE_LABELS[props.contentType];
  const isSet = props.mode === "set";
  const submitLabel = isSet ? "지정" : "해제";

  const onSubmit = async ({ adminComment }: HomeCurationFormValues) => {
    const comment = adminComment.trim() || undefined;
    try {
      await curationMutation.mutateAsync(
        props.mode === "set"
          ? { kind: "set", contentId: props.contentId, adminComment: comment }
          : { kind: "clear", adminComment: comment },
      );
      toast.success(isSet ? "홈 큐레이션으로 지정했어요." : "홈 큐레이션 지정을 해제했어요.");
      call.end();
      props.onSuccess?.();
    } catch (error) {
      const rejection = rejectionMessage(error);
      toast.error(rejection ?? ERROR_MESSAGE);
      // 고칠 입력이 없는 거부라 모달을 닫는다(다시 눌러도 같은 결과다).
      if (rejection) call.end();
    }
  };

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
      <DialogContent className="sm:max-w-md" onOpenAutoFocus={focusInitialElement}>
        <DialogHeader>
          <DialogTitle>{isSet ? "홈 큐레이션 지정" : "홈 큐레이션 해제"}</DialogTitle>
          <DialogDescription>
            <span className="font-medium text-foreground">{props.contentName}</span>
            {isSet
              ? `을(를) 홈 첫 화면의 ${typeLabel} 큐레이션으로 지정합니다. 필터 없는 홈을 여는 모든 사람에게 보여요.`
              : `의 ${typeLabel} 홈 큐레이션 지정을 해제합니다. 홈에서 큐레이션 섹션이 사라져요.`}
            {props.mode === "set" && props.replacingName !== null && (
              <>
                {" "}
                지금 지정된 <span className="font-medium text-foreground">{props.replacingName}</span>은(는) 내려가요.
              </>
            )}
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
            <Label htmlFor="home-curation-comment">관리자 코멘트 (선택)</Label>
            <Textarea
              id="home-curation-comment"
              placeholder="감사 로그에 남길 메모"
              rows={3}
              {...register("adminComment")}
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" autoFocus data-initial-focus onClick={() => call.end()}>
              취소
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "처리 중..." : submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
});

function rejectionMessage(error: unknown): string | null {
  if (!isApiError(error) || error.status !== 400) return null;
  if (typeof error.detail !== "object" || error.detail === null || !("code" in error.detail)) return null;
  const code = error.detail.code;
  return typeof code === "string" ? (REJECTION_MESSAGES[code] ?? null) : null;
}
