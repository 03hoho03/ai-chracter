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

import { useHomeNovelCurationMutation } from "@/entities/admin-novel";
import { apiErrorCode } from "@/shared/lib/api/client";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { focusInitialElement } from "@/shared/lib/callable/focusInitialElement";

/** 고칠 입력이 없는 거부라 모달을 닫는다(다시 눌러도 같은 결과다). 현황은 실패해도 새로 읽힌다. */
const REJECTION_MESSAGES: Record<string, string> = {
  NOT_PUBLICLY_LISTED: "지금 독자에게 보이지 않는 노벨이라 걸 수 없어요.",
  NOVEL_NOT_FOUND: "노벨을 찾을 수 없어요. 게시자가 지웠을 수 있어요.",
  HOME_NOVEL_CURATION_CONFLICT: "그사이 다른 운영자가 홈 노벨을 바꿨어요. 새 현황을 불러왔으니 확인하고 다시 걸어주세요.",
};

const ERROR_MESSAGE = "처리하지 못했어요. 잠시 후 다시 시도해주세요.";

/** 코멘트만 받고 검증이 없어 zod 스키마 없이 폼 값 타입만 둔다. */
type HomeNovelCurationFormValues = {
  adminComment: string;
};

type HomeNovelCurationConfirmModalProps = {
  novelTitle: string;
  position: number;
  /** 성공해 모달이 닫힌 뒤 부른다 — 상세 레이아웃이 하단 시트를 닫는다. 거부는 바뀐 것이 없어 부르지 않는다. */
  onSuccess?: () => void;
} & (
  | {
      mode: "set";
      novelId: string;
      /** 그 자리에 지금 걸린 다른 노벨 — 걸면 내려간다. */
      replacingTitle: string | null;
      /** 이 노벨이 지금 걸린 다른 자리 — 옮기면 그 자리는 빈다. */
      fromPosition: number | null;
    }
  | { mode: "clear" }
);

/** 홈 노벨 한 자리에 걸기·옮기기·비우기 확인. 로그인한 모든 회원의 홈에 바로 보이는 조작이라 무엇이 내려가고 어느 자리가
 * 비는지 보여 준다. 코멘트는 선택이다(게시자에게 불이익이 없고 되돌릴 수 있다). */
export const HomeNovelCurationConfirmModal = createCallable<HomeNovelCurationConfirmModalProps, void>(
  ({ call, ...props }) => {
    const curationMutation = useHomeNovelCurationMutation();
    const {
      register,
      handleSubmit,
      formState: { isSubmitting },
    } = useForm<HomeNovelCurationFormValues>({ defaultValues: { adminComment: "" } });
    const isSet = props.mode === "set";
    const isMove = props.mode === "set" && props.fromPosition !== null;
    let title = "홈 노벨 자리 비우기";
    if (isMove) title = "홈 노벨 자리 옮기기";
    else if (isSet) title = "홈 노벨에 걸기";
    let submitLabel = "비우기";
    if (isMove) submitLabel = "옮기기";
    else if (isSet) submitLabel = "걸기";
    if (isSubmitting) submitLabel = "처리 중...";

    const onSubmit = async ({ adminComment }: HomeNovelCurationFormValues) => {
      const comment = adminComment.trim() || undefined;
      try {
        await curationMutation.mutateAsync(
          props.mode === "set"
            ? { kind: "set", position: props.position, novelId: props.novelId, adminComment: comment }
            : { kind: "clear", position: props.position, adminComment: comment },
        );
        toast.success(isSet ? `홈 노벨 ${props.position}번 자리에 걸었어요.` : `홈 노벨 ${props.position}번 자리를 비웠어요.`);
        call.end();
        props.onSuccess?.();
      } catch (error) {
        const code = apiErrorCode(error);
        const rejection = code === null ? undefined : REJECTION_MESSAGES[code];
        toast.error(rejection ?? ERROR_MESSAGE);
        if (rejection) call.end();
      }
    };

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
        <DialogContent className="sm:max-w-md" onOpenAutoFocus={focusInitialElement}>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>
              <span className="font-medium text-foreground">{props.novelTitle}</span>
              {props.mode === "set" ? (
                <>
                  을(를) 홈 노벨 {props.position}번 자리에 겁니다. 로그인한 회원의 홈에 바로 보여요.
                  {props.fromPosition !== null && ` 지금 걸린 ${props.fromPosition}번 자리는 비어요.`}
                  {props.replacingTitle !== null && (
                    <>
                      {" "}
                      그 자리의 <span className="font-medium text-foreground">{props.replacingTitle}</span>은(는) 내려가요.
                    </>
                  )}
                </>
              ) : (
                `이(가) 걸린 홈 노벨 ${props.position}번 자리를 비웁니다. 홈에서 그 자리가 빠져요.`
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
              <Label htmlFor="home-novel-curation-comment">관리자 코멘트 (선택)</Label>
              <Textarea
                id="home-novel-curation-comment"
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
                {submitLabel}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  },
);
