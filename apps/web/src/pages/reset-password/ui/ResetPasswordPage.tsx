import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";

import { ResetPasswordForm } from "../../../features/reset-password";

interface ResetPasswordPageProps {
  token: string;
  isTokenValid: boolean;
}

export function ResetPasswordPage({ token, isTokenValid }: ResetPasswordPageProps) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-md">
        <div className="rounded-xl border border-border bg-card p-8">
          {isTokenValid ? (
            <>
              <div className="mb-6 flex flex-col gap-1">
                <h1 className="text-xl font-semibold tracking-tight text-foreground">
                  새 비밀번호 설정
                </h1>
                <p className="text-sm text-muted-foreground">
                  새로 사용할 비밀번호를 입력해주세요.
                </p>
              </div>

              <ResetPasswordForm token={token} />
            </>
          ) : (
            <>
              <div className="mb-6 flex flex-col gap-1">
                <h1 className="text-xl font-semibold tracking-tight text-foreground">
                  링크가 만료되었어요
                </h1>
                <p className="text-sm text-muted-foreground">
                  비밀번호 재설정 링크가 만료되었거나 유효하지 않아요. 다시 요청해주세요.
                </p>
              </div>

              <Button asChild size="lg" className="h-10 w-full">
                <Link to="/forgot-password">재설정 다시 요청하기</Link>
              </Button>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
