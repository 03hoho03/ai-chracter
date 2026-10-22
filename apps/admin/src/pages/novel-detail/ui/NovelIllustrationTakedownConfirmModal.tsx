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
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useNovelIllustrationTakedownMutation, type AdminNovelIllustration } from "@/entities/admin-novel";
import { apiErrorCode } from "@/shared/lib/api/client";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { focusInitialElement } from "@/shared/lib/callable/focusInitialElement";

import { illustrationAlt, illustrationFrameStyle, ILLUSTRATION_SOURCE_LABELS } from "../lib/chapterIllustrations";

/** 모달 안 축소본의 높이 상한 — 어느 그림인지 눈으로 확인할 만큼만. */
const PREVIEW_MAX_HEIGHT_PX = 160;

/** 고칠 입력이 없는 결과 — 그사이 그림 상태가 바뀌었다. 모달을 닫고 화는 새로 읽힌다. */
const SETTLED_MESSAGES: Record<string, string> = {
  NOVEL_ILLUSTRATION_NOT_FOUND: "이 그림은 이제 어느 소설에도 쓰이지 않아요.",
  NOVEL_ILLUSTRATION_ALREADY_TAKEN_DOWN: "이 그림은 이미 내려가 있어요.",
};

const ALREADY_TAKEN_DOWN_MESSAGE = "이미 내려가 있어요. 같은 파일이 먼저 내려가 있어 이 그림 자리에도 처음 적은 사유가 보여요.";
/** 같은 입력으로 다시 누르면 되는 실패 — 모달과 적은 사유를 그대로 둔다. */
const UNAVAILABLE_MESSAGE = "그림 파일을 읽지 못해 내리지 못했어요. 잠시 후 다시 시도해주세요.";
const ERROR_MESSAGE = "처리하지 못했어요. 사유는 그대로 남아 있으니 다시 시도해주세요.";

const REASON_ID = "novel-illustration-takedown-reason";

const takedownSchema = z.object({
  reason: z.string().trim().min(1, "독자에게 보일 사유를 입력해주세요."),
});

type TakedownFormValues = z.infer<typeof takedownSchema>;

type NovelIllustrationTakedownConfirmModalProps = {
  illustration: AdminNovelIllustration;
};

/**
 * 공개본 화 펼침의 "그림 내리기" 확인. 내림은 그 그림 파일 단위라 이 그림을 쓴 모든 소설의 모든 판에서 자리가 비고 되돌리는
 * 길이 없다 — 그래서 내릴 그림의 축소본을 함께 보여 운영자가 눈으로 확인하게 한다. 사유는 독자 화면의 그림 자리에 그대로
 * 보이고 감사 로그의 조치 사유로도 남아 필수다(서버도 공백뿐이면 422). 같은 파일이 다른 자산으로 이미 내려가 있으면 서버가
 * 새로 내리지 않고 "이미 내려감"으로 답한다 — 실패가 아니라 결과로 알린다.
 */
export const NovelIllustrationTakedownConfirmModal = createCallable<NovelIllustrationTakedownConfirmModalProps, void>(
  ({ call, illustration }) => {
    const takedownMutation = useNovelIllustrationTakedownMutation(illustration.assetId);
    const {
      control,
      register,
      handleSubmit,
      formState: { errors, isSubmitting },
    } = useForm<TakedownFormValues>({
      resolver: zodResolver(takedownSchema),
      defaultValues: { reason: "" },
    });
    const reasonLength = useWatch({ control, name: "reason" }).trim().length;

    const onSubmit = async ({ reason }: TakedownFormValues) => {
      try {
        const result = await takedownMutation.mutateAsync({ reason: reason.trim() });
        if (result.alreadyTakenDown) toast.info(ALREADY_TAKEN_DOWN_MESSAGE);
        else toast.success("그림을 내렸어요.");
        call.end();
      } catch (error) {
        const code = apiErrorCode(error);
        if (code === "NOVEL_ILLUSTRATION_UNAVAILABLE") {
          toast.error(UNAVAILABLE_MESSAGE);
          return;
        }
        const settled = code === null ? undefined : SETTLED_MESSAGES[code];
        if (settled) {
          toast.info(settled);
          call.end();
          return;
        }
        toast.error(ERROR_MESSAGE);
      }
    };

    return (
      // 요청 중에는 닫지 않는다 — 닫은 뒤 끝나면 내려졌는지 알릴 자리가 없다.
      <Dialog open={!call.ended} onOpenChange={(open) => !open && !isSubmitting && call.end()}>
        <DialogContent className="sm:max-w-md" onOpenAutoFocus={focusInitialElement}>
          <DialogHeader>
            <DialogTitle>그림 내리기</DialogTitle>
            <DialogDescription className="break-keep">
              이 그림을 쓴 <span className="font-medium text-foreground">모든 소설의 모든 판</span>에서 그림 자리가 비고, 아래
              사유가 독자에게 그대로 보여요. 같은 파일을 다시 올려도 공개할 수 없어요. 구매 환급은 없고{" "}
              <span className="font-medium text-foreground">되돌릴 수 없어요</span>. 소설 전체를 닫아야 하면 노벨 이용제한을
              함께 쓰세요.
              {illustration.source === "original" && " 원작 작품 화면의 이 그림은 그대로예요 — 노벨 삽화에서만 내려가요."}
            </DialogDescription>
          </DialogHeader>

          <form
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              void handleSubmit(onSubmit)(event);
            }}
            className="flex min-h-0 flex-1 flex-col gap-4"
          >
            <DialogBody className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <TakedownPreview illustration={illustration} />
                <p className="text-xs break-keep text-muted-foreground">
                  {ILLUSTRATION_SOURCE_LABELS[illustration.source]} · {illustrationAlt(illustration)} · 자산 id{" "}
                  <span className="break-all">{illustration.assetId}</span>
                </p>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor={REASON_ID}>독자에게 보일 사유 (필수)</Label>
                <Textarea
                  id={REASON_ID}
                  rows={3}
                  placeholder="예: 운영정책에 맞지 않는 장면이 담겨 이 그림을 내렸어요."
                  aria-invalid={!!errors.reason}
                  aria-describedby={errors.reason ? `${REASON_ID}-error ${REASON_ID}-help` : `${REASON_ID}-help`}
                  {...register("reason")}
                />
                {errors.reason && (
                  <p id={`${REASON_ID}-error`} role="alert" className="text-xs text-destructive-text">
                    {errors.reason.message}
                  </p>
                )}
                <div className="flex items-start justify-between gap-3 text-xs text-muted-foreground">
                  <p id={`${REASON_ID}-help`} className="break-keep">
                    독자 화면에서는 세 줄까지만 보여요. 한두 문장으로 적어 주세요. 감사 로그의 조치 사유로도 남아요.
                  </p>
                  <span className="shrink-0 tabular-nums" aria-hidden>
                    {reasonLength}자
                  </span>
                </div>
              </div>
            </DialogBody>

            <DialogFooter>
              <Button type="button" variant="outline" autoFocus data-initial-focus onClick={() => call.end()}>
                취소
              </Button>
              <Button type="submit" variant="destructive" disabled={isSubmitting}>
                {isSubmitting ? "내리는 중..." : "그림 내리기"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  },
);

/** 내릴 그림의 축소본. 원작 이용제한으로 가려진 그림은 서버가 주소를 주지 않아 보일 수 없다 — 그 사정을 같은 자리에 적는다. */
function TakedownPreview({ illustration }: { illustration: AdminNovelIllustration }) {
  if (illustration.url === null) {
    return (
      <p className="rounded-lg border border-dashed border-border p-3 text-sm break-keep text-muted-foreground">
        원작 작품이 이용제한 중이라 여기서는 그림을 볼 수 없어요.
      </p>
    );
  }
  const sizedStyle = illustrationFrameStyle(illustration.width, illustration.height, PREVIEW_MAX_HEIGHT_PX);
  return (
    <div
      className={cn("shrink-0 self-start overflow-hidden rounded-lg bg-secondary", sizedStyle === undefined && "aspect-3/4 h-40")}
      style={sizedStyle}
    >
      <img src={illustration.url} alt={illustrationAlt(illustration)} decoding="async" className="size-full object-contain" />
    </div>
  );
}
