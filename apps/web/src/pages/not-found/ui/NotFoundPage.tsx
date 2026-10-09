import { Link, useCanGoBack, useRouter } from "@tanstack/react-router";
import { FileQuestion } from "lucide-react";

import { Button } from "@ai-character-chat/ui/components/button";

/** 어느 라우트에도 맞지 않는 주소의 화면. 루트 라우트가 아웃렛 자리에 그리므로 전역 헤더·푸터는 주소에 따라
 * 평소대로 붙는다(`/builder/…`처럼 헤더를 숨기는 접두사 아래면 헤더 없이 이 화면만 남아, 홈으로 가는 버튼을 늘 둔다).
 * 모양은 공지·문의 상세의 "찾을 수 없음" 상태를 따르되, 이 안내가 페이지의 전부라 제목은 `h1`이다.
 * '이전 페이지'는 앱 안에서 넘어왔을 때만 보인다 — 외부 링크로 바로 들어왔으면 뒤로 가기가 사이트를 떠난다. */
export function NotFoundPage() {
  const router = useRouter();
  const canGoBack = useCanGoBack();

  return (
    <main className="mx-auto flex max-w-2xl flex-col items-center gap-3 px-4 py-16 text-center break-keep sm:px-6">
      <FileQuestion aria-hidden className="size-8 text-muted-foreground" />
      <h1 className="text-lg font-semibold text-foreground">페이지를 찾을 수 없어요</h1>
      <p className="text-sm text-muted-foreground">주소가 잘못됐거나 사라진 페이지예요.</p>
      <div className="mt-3 flex flex-wrap justify-center gap-2">
        {canGoBack && (
          <Button type="button" variant="outline" onClick={() => router.history.back()}>
            이전 페이지
          </Button>
        )}
        <Button asChild>
          <Link to="/">홈으로</Link>
        </Button>
      </div>
    </main>
  );
}
