import type { Visibility } from "@/features/build-character";

/** 공개범위 값마다 붙는 화면 글자. 값 목록(`VISIBILITY_VALUES`)은 스키마가 단일 소스다. 등록 탭 토글과 첫 발행
 * 확인창이 함께 읽는다 — 확인창이 방금 고른 토글과 같은 글자를 보여야 같은 것으로 읽힌다. */
export const VISIBILITY_LABELS: Record<Visibility, string> = {
  public: "전체공개",
  link: "링크공개",
  private: "비공개",
};
