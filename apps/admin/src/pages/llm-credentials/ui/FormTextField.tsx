import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import type { UseFormRegisterReturn } from "react-hook-form";

type FormTextFieldProps = {
  id: string;
  label: string;
  hint?: string;
  /** 숫자 칸도 문자열로 받는다 — 키보드만 숫자판으로 고른다. */
  inputMode?: "text" | "decimal" | "numeric";
  isRequired?: boolean;
  registration: UseFormRegisterReturn;
  error: string | undefined;
};

/** 자격 폼의 한 줄 입력칸(이름·충전액·임계). 도움말은 칸 위, 오류는 칸 아래이고 둘 다 칸의 설명으로 읽힌다. */
export function FormTextField({
  id,
  label,
  hint,
  inputMode = "text",
  isRequired = false,
  registration,
  error,
}: FormTextFieldProps) {
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint === undefined ? undefined : hintId, error === undefined ? undefined : errorId]
    .filter((value) => value !== undefined)
    .join(" ");

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {hint !== undefined && (
        <p id={hintId} className="text-xs break-keep text-muted-foreground">
          {hint}
        </p>
      )}
      <Input
        id={id}
        type="text"
        inputMode={inputMode}
        autoComplete="off"
        aria-required={isRequired}
        aria-invalid={error !== undefined}
        aria-describedby={describedBy === "" ? undefined : describedBy}
        {...registration}
      />
      {error !== undefined && (
        <p id={errorId} role="alert" className="text-xs break-keep text-destructive-text">
          {error}
        </p>
      )}
    </div>
  );
}
