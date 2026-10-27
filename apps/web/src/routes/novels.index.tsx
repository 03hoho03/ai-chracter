import { createFileRoute, redirect } from "@tanstack/react-router";

// 목록은 `.index.tsx`로 둔다 — `novels.tsx`로 두면 `novels.$novelId.tsx`가 그 자식으로 중첩돼 URL만 바뀌고
// 화면은 목록이 그대로 보인다(`inquiries.index.tsx`와 같은 이유). 그래서 아래 리다이렉트도 작품 정보·편집 보드·화
// 읽기 주소에는 닿지 않는다.
// 옛 소설 목록 주소의 북마크와 로그인 복귀 주소를 살리려고 남긴 라우트다. 내 소설은 이제 스튜디오 홈의 소설 유형으로
// 본다. 서버 301 이 아니라 여기서 넘기는 이유는 브라우저가 301 을 캐시해 되돌리기가 안 되기 때문이다. 허용 여부와
// 세션은 여기서 보지 않는다 — 소설화가 닫힌 계정의 소설 유형은 스튜디오 홈이 전체로 접고, 비로그인은 스튜디오 홈이
// 로그인으로 보낸다(한 규칙을 두 곳에 두지 않는다).
export const Route = createFileRoute("/novels/")({
  beforeLoad: () => redirect({ to: "/studio", search: { type: "novel" }, replace: true, throw: true }),
});
