import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import type { ReactNode } from "react";
import type { UseFormRegisterReturn } from "react-hook-form";

import { defaultUserNameIssue, PERSONA_NAME_MAX_LENGTH } from "@/entities/persona";
import { FALLBACK_USER_NAME } from "@/shared/lib/text/authorMacros";

type DefaultUserNameFieldProps = {
  id: string;
  label: ReactNode;
  contentType: "story" | "character";
  /** 입력칸의 지금 값. 오류는 입력하는 동안 이 값으로 바로 보인다. */
  value: string;
  /** 발행 검사가 이 칸에 건 오류. 입력 중 오류가 있으면 그쪽이 먼저다(같은 규칙이라 문구도 같다). */
  publishError: string | undefined;
  registration: UseFormRegisterReturn;
};

/**
 * 작품 기본 이름 칸. 작가 글의 `{{user}}` 는 대화 프로필 이름으로 바뀌고, 프로필이 없는 사람에게는 이 이름이 보인다.
 * 매크로를 쓸 수 있다는 안내를 글 칸마다 붙이지 않고 이 칸 설명 한 줄에 모은다 — 그 이름이 어디에 쓰이는지 말하는 자리가
 * 곧 매크로를 소개하는 자리다.
 *
 * 서버가 받지 않을 값은 입력하는 동안 칸 아래에 바로 알린다. 자동저장은 폼 검증을 거치지 않으므로 그동안 이 칸만 빼고
 * 저장하며(각 빌더의 `formToServer`), 오류 문장이 그 사실을 함께 말한다.
 */
export function DefaultUserNameField({
  id,
  label,
  contentType,
  value,
  publishError,
  registration,
}: DefaultUserNameFieldProps) {
  const liveError = defaultUserNameIssue(value);
  const error = liveError ?? publishError;
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        placeholder={`비워 두면 '${FALLBACK_USER_NAME}'`}
        maxLength={PERSONA_NAME_MAX_LENGTH}
        autoComplete="off"
        aria-invalid={!!error}
        aria-describedby={error ? `${hintId} ${errorId}` : hintId}
        {...registration}
      />
      <p id={hintId} className="text-sm break-keep text-muted-foreground">
        작품 글에 <span className="text-foreground">{"{{user}}"}</span>를 쓰면 대화하는 사람의 프로필 이름으로
        {contentType === "character" ? (
          <>
            , <span className="text-foreground">{"{{char}}"}</span>를 쓰면 캐릭터 이름으로
          </>
        ) : null}{" "}
        바뀌어요. 프로필이 없는 사람에게는 이 이름이 보여요.
      </p>
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-destructive-text">
          {liveError !== null ? `${liveError} — 고칠 때까지 이 칸은 저장되지 않아요` : error}
        </p>
      ) : null}
    </div>
  );
}
