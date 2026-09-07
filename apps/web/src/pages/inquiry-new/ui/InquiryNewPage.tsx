import { Link } from "@tanstack/react-router";

import { SubmitInquiryForm } from "@/features/submit-inquiry";

/** `/inquiries/new` — 문의 작성 폼. `requireSession`으로 로그인 사용자만 접근한다(D-6).
 * 프로필 메뉴 `문의하기` 항목의 도착지이자, 그 항목의 라벨과 이 h1이 같은 문자열이어야 하는
 * 불변식의 대상이다(D-12, `ProfileMenu.tsx` 참고). */
export function InquiryNewPage() {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-4 sm:px-6 py-10">
      <div className="flex flex-col gap-1.5">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">문의하기</h1>
        <p className="text-sm break-keep text-muted-foreground">
          지금까지 남긴 문의는{" "}
          <Link
            to="/inquiries"
            className="font-medium whitespace-nowrap text-primary hover:underline focus-visible:underline"
          >
            내 문의 내역
          </Link>
          에서 확인할 수 있어요.
        </p>
      </div>
      <SubmitInquiryForm />
    </main>
  );
}
