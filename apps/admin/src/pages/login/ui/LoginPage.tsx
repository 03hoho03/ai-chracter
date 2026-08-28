import { LoginForm } from "@/features/login";

type LoginPageProps = {
  redirectTo?: string;
}

export function LoginPage({ redirectTo }: LoginPageProps) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center gap-1 text-center">
          <span className="text-sm font-semibold text-primary">AI 캐릭터 챗 관리자</span>
        </div>

        <div className="rounded-xl border border-border bg-card p-8">
          <div className="mb-6 flex flex-col gap-1">
            <h1 className="text-xl font-semibold tracking-tight text-foreground">관리자 로그인</h1>
            <p className="text-sm text-muted-foreground">관리자 계정 이메일과 비밀번호로 로그인해주세요.</p>
          </div>

          <LoginForm redirectTo={redirectTo} />
        </div>
      </div>
    </main>
  );
}
