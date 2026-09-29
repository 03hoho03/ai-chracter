import { describe, expect, it } from "vitest";

import { creationGuidePath } from "@/shared/config/creationGuide";

// 셸 소스는 문자열로 읽는다 — 빌더 셸은 node 환경에서 import 하면 모듈 최상위 `localStorage` 접근에서 죽는다.
import shellSource from "./StoryBuilderShell.tsx?raw";

describe("StoryBuilderShell", () => {
  // 상단바의 작성 가이드 링크가 스토리 가이드를 가리킨다(다른 빌더의 가이드로 새지 않는다).
  it("links the top bar to the story guide", () => {
    expect(shellSource).toContain(`guidePath="${creationGuidePath("story")}"`);
  });
});
