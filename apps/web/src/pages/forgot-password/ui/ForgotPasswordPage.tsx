import { ForgotPasswordForm } from "@/features/forgot-password";

export function ForgotPasswordPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-md">
        <div className="rounded-xl border border-border bg-card p-8">
          <div className="mb-6 flex flex-col gap-1">
            <h1 className="text-xl font-semibold tracking-tight text-foreground">
              비밀번호 찾기
            </h1>
            <p className="text-sm text-muted-foreground">
              가입하신 이메일을 입력하면 재설정 링크를 보내드려요.
            </p>
          </div>

          <ForgotPasswordForm />
        </div>
      </div>
    </main>
  );
}
