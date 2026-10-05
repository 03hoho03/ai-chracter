import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { zodResolver } from "@hookform/resolvers/zod";
import { useId } from "react";
import { useForm } from "react-hook-form";

import { toNovelActionError, useSetProtagonistNameMutation } from "@/entities/novel";
import { isApiError } from "@/shared/api/client";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { createProtagonistNameSchema, type ProtagonistNameFormValues } from "../model/protagonistNameSchema";

type ProtagonistNameModalProps = {
  novelId: string;
  /** 상세의 `limits.protagonistNameMaxLength`. */
  maxLength: number;
};

/** 첫 장을 만들기 전에 주인공(이용자 쪽) 이름을 받는다. 서버는 대화 프로필 이름(없으면 작품 기본 이름)으로 미리
 * 채워 두고, 둘 다 없을 때만 이름이 비어 있다 — 비어 있으면 장 생성이 차감 전에 거절된다.
 *
 * 저장 뒤 동작이 늘 같아(이름 저장 → 상세 캐시 갱신) 자체 호출형이다. `true` 는 저장했다, `false` 는 그만뒀다.
 * 빈칸으로 시작하고 첫 칸이 포커스를 받는다(이 모달은 언제나 이용자가 누른 버튼으로 열린다). */
export const ProtagonistNameModal = createCallable<ProtagonistNameModalProps, boolean>(({ call, novelId, maxLength }) => {
  const nameId = useId();
  const form = useForm<ProtagonistNameFormValues>({
    resolver: zodResolver(createProtagonistNameSchema(maxLength)),
    defaultValues: { protagonistName: "" },
  });
  const { mutateAsync, isPending } = useSetProtagonistNameMutation();
  const isSubmitting = form.formState.isSubmitting || isPending;
  const { errors } = form.formState;

  async function handleValidSubmit(values: ProtagonistNameFormValues) {
    try {
      await mutateAsync({ novelId, protagonistName: values.protagonistName });
      call.end(true);
    } catch (error) {
      // 재동의가 필요하면 전역 재동의 모달이 뜬다 — 그 위에 이 모달을 남겨 두지 않는다.
      if (toNovelActionError(error, "edit") === null) {
        call.end(false);
        return;
      }
      // 요청 검증 422 는 클라이언트 규칙이 서버와 어긋났다는 뜻이라(서버가 더 막는 문자) 칸 오류로 둔다.
      if (isApiError(error) && error.status === 422) {
        form.setError("protagonistName", { message: "이 이름은 쓸 수 없어요. 다른 이름을 입력해주세요" });
        return;
      }
      form.setError("root", { message: "이름을 저장하지 못했어요. 잠시 후 다시 시도해주세요." });
    }
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(false)}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>주인공 이름을 정해주세요</DialogTitle>
          <DialogDescription className="break-keep">
            소설 속에서 내 쪽 인물을 부를 이름이에요. 대화 프로필 이름이 없어서 여기서 받아요.
          </DialogDescription>
        </DialogHeader>

        <form
          noValidate
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            // 저장 중 `disabled` 는 누른 버튼의 포커스를 날린다 — `aria-disabled` 로 두고 여기서 막는다.
            if (isSubmitting) return;
            void form.handleSubmit(handleValidSubmit)(event);
          }}
        >
          {errors.root && (
            <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text">
              {errors.root.message}
            </p>
          )}

          <div className="flex flex-col gap-1.5">
            <Label htmlFor={nameId}>주인공 이름</Label>
            <Input
              id={nameId}
              autoFocus
              autoComplete="off"
              aria-invalid={!!errors.protagonistName}
              aria-describedby={errors.protagonistName ? `${nameId}-error` : undefined}
              {...form.register("protagonistName")}
            />
            {errors.protagonistName && (
              <p id={`${nameId}-error`} role="alert" className="text-xs break-keep text-destructive-text">
                {errors.protagonistName.message}
              </p>
            )}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end(false)}>
              취소
            </Button>
            <Button type="submit" aria-disabled={isSubmitting} className="aria-disabled:opacity-65">
              {isSubmitting ? "저장 중…" : "이름 정하기"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
});
