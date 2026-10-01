import { LoginForm, type LoginErrorParam, type SignupMethod } from "@/features/login";

type LoginPageProps = {
  redirectTo?: string;
  errorCode?: LoginErrorParam;
  errorMethod?: SignupMethod;
}

export function LoginPage({ redirectTo, errorCode, errorMethod }: LoginPageProps) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-md">
        <div className="rounded-xl border border-border bg-card p-8">
          <div className="mb-6 flex flex-col gap-1">
            <h1 className="text-xl font-semibold tracking-tight text-foreground">로그인</h1>
            <p className="text-sm text-muted-foreground">이메일이나 카카오·구글 계정으로 로그인해주세요.</p>
          </div>

          <LoginForm redirectTo={redirectTo} errorCode={errorCode} errorMethod={errorMethod} />
        </div>
      </div>
    </main>
  );
}
