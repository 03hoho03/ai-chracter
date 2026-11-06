import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import type { UseFormRegisterReturn } from "react-hook-form";

type ReasonFieldProps = {
  id: string;
  registration: UseFormRegisterReturn<"reason">;
  error: string | undefined;
};

/** 기능 스위치 저장의 사유 칸. 사유는 이력과 운영 알림에 그대로 실려 누가 읽는지를 늘 적는다. */
export function ReasonField({ id, registration, error }: ReasonFieldProps) {
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>사유 (필수)</Label>
      <p id={hintId} className="text-xs break-keep text-muted-foreground">
        변경 이력과 운영 디스코드 알림에 그대로 실려요. 회원 이메일·닉네임 같은 개인정보는 적지 마세요.
      </p>
      <Textarea
        id={id}
        rows={3}
        placeholder="예: 요약 품질 사고 대응, 약관 개정 시행"
        aria-required
        aria-invalid={error !== undefined}
        aria-describedby={error === undefined ? hintId : `${hintId} ${errorId}`}
        {...registration}
      />
      {error !== undefined && (
        <p id={errorId} role="alert" className="text-xs text-destructive-text">
          {error}
        </p>
      )}
    </div>
  );
}
