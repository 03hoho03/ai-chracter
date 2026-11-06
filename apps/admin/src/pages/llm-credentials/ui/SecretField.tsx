import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import type { UseFormRegisterReturn } from "react-hook-form";

type SecretFieldProps = {
  id: string;
  registration: UseFormRegisterReturn<"apiKey">;
  error: string | undefined;
};

/**
 * 추가·키 교체가 함께 쓰는 API 키 칸. 비밀번호 칸(`type="password"`)이 아니라 일반 입력칸이다 — 비밀번호 칸이면 브라우저가 저장
 * 성공 뒤 "비밀번호 저장"을 제안하고, 누르면 키가 동기화되는 비밀번호 저장소로 간다. 일반 입력칸에는 그 제안 경로가 없다. 대가는
 * 붙여넣는 동안 키가 화면에 보인다는 것이다(운영자 자기 계정의 키이고, 저장한 뒤에는 끝 4자리만 남는다).
 *
 * 정산 수취 정보 교체 칸과 같이 자동 완성을 끄고, 확장 프로그램형 비밀번호 관리자가 일반 칸도 저장할 값으로 잡지 않게 그 관리자들이
 * 읽는 무시 표식을 단다. 맞춤법 검사는 칸 내용을 맞춤법 서비스로 보내는 브라우저 설정이 있어 끄고, 자동 대문자·자동 고침은 키를
 * 바꿔 끈다. 칸은 서버 값으로 채우지 않는다.
 */
export function SecretField({ id, registration, error }: SecretFieldProps) {
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>API 키</Label>
      <p id={hintId} className="text-xs break-keep text-muted-foreground">
        저장하면 칸을 비우고 다시 보여 주지 않아요. 저장한 뒤에는 끝 4자리와 지문만 보여요.
      </p>
      <Input
        id={id}
        type="text"
        autoComplete="off"
        spellCheck={false}
        autoCapitalize="none"
        autoCorrect="off"
        data-1p-ignore
        data-lpignore="true"
        data-bwignore
        data-form-type="other"
        aria-required
        aria-invalid={error !== undefined}
        aria-describedby={error === undefined ? hintId : `${hintId} ${errorId}`}
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
