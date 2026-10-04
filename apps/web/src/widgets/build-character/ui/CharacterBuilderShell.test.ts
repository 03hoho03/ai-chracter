import { describe, expect, it } from "vitest";

// 셸 소스는 문자열로 읽는다 — 빌더 셸은 node 환경에서 import 하면 모듈 최상위 `localStorage` 접근에서 죽는다.
import shellSource from "./CharacterBuilderShell.tsx?raw";

describe("CharacterBuilderShell", () => {
  // 상단바의 작성 가이드 링크가 캐릭터 가이드에서 지금 열린 탭의 단계 페이지를 가리킨다(다른 빌더의 가이드로 새지
  // 않고, 탭을 옮기면 링크도 따라간다). 단계 id 가 탭 id 와 같다는 것은 원고 검사가 따로 본다.
  it("links the top bar to the character guide step of the open tab", () => {
    expect(shellSource).toContain(`guidePath={creationGuidePath("character", activeTab)}`);
    expect(shellSource).toMatch(/const \[activeTab, setActiveTab\] = useState<CharacterBuilderTab>\(/);
  });
});
