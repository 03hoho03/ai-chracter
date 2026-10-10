import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { useFormContext } from "react-hook-form";

import type { SignUpFormValues } from "../model/signUpSchema";

type PersonaNameFieldProps = {
  /** 스텝의 다른 칸과 같은 id 접두사(`signup`·`onboarding`). */
  idPrefix: string;
};

/** 첫 대화 프로필 이름(선택). 비워도 가입되고, 그러면 처음 대화를 시작할 때 이름을 받는다. 닉네임으로 미리 채우지 않는다 —
 * 이 이름은 캐릭터에게 보내지는데 닉네임은 프롬프트에 싣지 않는 계정 정보다(서버도 닉네임으로 채우지 않는다). */
export function PersonaNameField({ idPrefix }: PersonaNameFieldProps) {
  const {
    register,
    formState: { errors },
  } = useFormContext<SignUpFormValues>();
  const id = `${idPrefix}-persona-name`;
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>
        대화에서 쓸 이름 <span className="font-normal text-muted-foreground">(선택)</span>
      </Label>
      <Input
        id={id}
        autoComplete="off"
        placeholder="캐릭터가 나를 부를 이름"
        aria-invalid={!!errors.personaName}
        aria-describedby={errors.personaName ? `${errorId} ${hintId}` : hintId}
        {...register("personaName")}
      />
      {errors.personaName && (
        <p id={errorId} role="alert" className="text-xs break-keep text-destructive-text">
          {errors.personaName.message}
        </p>
      )}
      <p id={hintId} className="text-xs break-keep text-muted-foreground">
        비워 두고 넘어가도 돼요. 처음 대화를 시작할 때 정할 수 있어요.
      </p>
    </div>
  );
}
