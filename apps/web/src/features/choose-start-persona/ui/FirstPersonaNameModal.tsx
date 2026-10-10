import { useId } from "react";
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
import { useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { isLegalReconsentRequiredError } from "@/entities/legal";
import { personaKeys, useCreatePersonaMutation, type Persona, type PersonaList } from "@/entities/persona";
import { isApiError } from "@/shared/api/client";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { firstPersonaNameSchema, type FirstPersonaNameFormValues } from "../model/firstPersonaNameSchema";

const GENERIC_ERROR_MESSAGE = "이름을 저장하지 못했어요. 잠시 후 다시 시도해주세요.";

/**
 * 대화 프로필이 하나도 없는 사람이 새 대화를 열 때 이름 하나를 받아 첫 프로필(곧 기본)을 만든다. 만든 프로필을 돌려주고,
 * 닫으면 undefined 라 호출부는 대화를 시작하지 않는다.
 *
 * 저장 뒤 동작이 늘 같아(프로필 생성 → 목록 캐시 반영) 자체 호출형이다. 방은 이 모달이 아니라 호출부가 만든다 — 그래야
 * 방 생성이 실패해도 프로필은 이미 있어서, 다시 누르면 이름을 또 묻지 않고 방금 만든 프로필로 방만 만든다.
 * 이름은 빈칸으로 시작한다(닉네임은 프롬프트에 싣지 않는 계정 정보라 미리 채우지 않는다).
 */
export const FirstPersonaNameModal = createCallable<void, Persona | undefined>(({ call }) => {
  const queryClient = useQueryClient();
  const nameId = useId();
  const hintId = `${nameId}-hint`;
  const form = useForm<FirstPersonaNameFormValues>({
    resolver: zodResolver(firstPersonaNameSchema),
    defaultValues: { name: "" },
  });
  const createMutation = useCreatePersonaMutation();
  const isSubmitting = form.formState.isSubmitting || createMutation.isPending;
  const { errors } = form.formState;

  async function handleValidSubmit(values: FirstPersonaNameFormValues) {
    form.clearErrors("root");
    try {
      const persona = await createMutation.mutateAsync({
        name: values.name.trim(),
        gender: null,
        description: "",
        setAsDefault: true,
      });
      // 생성 훅이 목록을 다시 읽지만, 그 조회가 실패하면 캐시가 "0개"로 남아 다음 시작에서 이 모달이 또 떠 프로필이
      // 하나 더 생긴다. 방금 만든 것을 캐시에 직접 넣어 둔다.
      queryClient.setQueryData<PersonaList>(personaKeys.list(), (old) =>
        old === undefined || old.items.some((item) => item.id === persona.id)
          ? old
          : { ...old, items: [...old.items, persona], defaultPersonaId: old.defaultPersonaId ?? persona.id },
      );
      call.end(persona);
    } catch (error) {
      // 재동의가 필요하면 전역 재동의 모달이 뜬다 — 그 위에 이 모달을 남기거나 오류 문구로 덮지 않고, 대화도 시작하지 않는다.
      if (isLegalReconsentRequiredError(error)) {
        call.end(undefined);
        return;
      }
      // 요청 검증 422 는 클라이언트 규칙이 서버와 어긋났다는 뜻이라(서버가 더 막는 문자) 칸 오류로 둔다.
      if (isApiError(error) && error.status === 422) {
        form.setError("name", { message: "이 이름은 쓸 수 없어요. 다른 이름을 입력해주세요" });
        return;
      }
      // 409 는 그사이 다른 탭에서 프로필을 만들어 이 판정(0개)이 낡았다는 뜻이다 — 이름을 더 받지 않고 서버 문구를 보이며
      // 닫는다. 생성 훅이 목록을 다시 받으므로 다시 누르면 있는 프로필로 시작한다.
      if (isApiError(error) && error.status === 409) {
        toast.error(error.message);
        call.end(undefined);
        return;
      }
      form.setError("root", { message: GENERIC_ERROR_MESSAGE });
    }
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(undefined)}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>대화에서 쓸 이름</DialogTitle>
          <DialogDescription className="break-keep">
            캐릭터가 나를 이 이름으로 불러요. 대화 프로필로 저장돼서 다음 대화에도 쓰이고, 대화 프로필 화면에서 언제든
            바꿀 수 있어요.
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
            <Label htmlFor={nameId}>이름</Label>
            {/* 이 모달은 언제나 사용자가 누른 플레이·새 대화 버튼으로 열린다 — 첫 칸이 포커스를 받는다. */}
            <Input
              id={nameId}
              autoFocus
              autoComplete="off"
              placeholder="캐릭터가 나를 부를 이름"
              aria-invalid={!!errors.name}
              aria-describedby={errors.name ? `${nameId}-error` : hintId}
              {...form.register("name")}
            />
            {errors.name ? (
              <p id={`${nameId}-error`} role="alert" className="text-xs break-keep text-destructive-text">
                {errors.name.message}
              </p>
            ) : (
              <p id={hintId} className="text-xs break-keep text-muted-foreground">
                성별이나 나에 대한 설명은 나중에 대화 프로필에서 더할 수 있어요.
              </p>
            )}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end(undefined)}>
              취소
            </Button>
            <Button type="submit" aria-disabled={isSubmitting} className="aria-disabled:opacity-65">
              {isSubmitting ? "저장 중…" : "이 이름으로 시작"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
});
