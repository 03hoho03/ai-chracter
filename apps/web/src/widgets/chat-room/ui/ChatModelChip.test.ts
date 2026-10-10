import { describe, expect, it } from "vitest";

// 화면 소스는 문자열로 읽는다 — 이 위젯은 node 환경에서 import 하면 모듈 최상위 `localStorage` 접근에서 죽는다.
import chipNameSource from "../model/chatModelChip.ts?raw";
import moreNavSource from "./ChatMoreNav.tsx?raw";
import viewSource from "./ChatRoomView.tsx?raw";

const chips = viewSource.match(/<ChatModelChip\b[\s\S]*?\/>/g) ?? [];
const guardedChips = viewSource.match(/\bchatModelChipLabel\s*&&\s*\(?\s*<ChatModelChip\b[\s\S]*?\/>/g) ?? [];

describe("chat model chip wiring", () => {
  // 모델 칩과 ⋮ 패널의 「AI 모델」은 같은 기능 스위치 판정을 써서 스위치가 꺼지면 둘 다 사라져야 한다. 기능 이름을 각자 적으면 한쪽만 바뀌어 새는 길이 생긴다.
  it("칩 판정과 ⋮ 항목이 같은 게이트 상수를 쓴다", () => {
    expect(chipNameSource.match(/isFeatureItemVisible\(CHAT_MODEL_FEATURE_GATE,/g) ?? []).toHaveLength(1);
    expect(moreNavSource.match(/\.\.\.CHAT_MODEL_FEATURE_GATE\b/g) ?? []).toHaveLength(1);
  });

  it("두 곳 모두 기능 이름 문자열을 직접 적지 않는다", () => {
    expect(chipNameSource).not.toContain('"chat_premium_models"');
    expect(moreNavSource).not.toContain('"chat_premium_models"');
  });

  it("화면에 칩이 헤더와 입력 바 두 자리에 있다 — 0건이면 아래 검사가 헛돈다", () => {
    expect(chips).toHaveLength(2);
    expect(chips.filter((chip) => chip.includes('placement="header"'))).toHaveLength(1);
    expect(chips.filter((chip) => chip.includes('placement="input-bar"'))).toHaveLength(1);
  });

  // 두 칩 모두 판정 결과를 이름으로 받고, 같은 값이 비면 그리지 않아야 한다. 한 자리라도 가드가 빠지면 숨겨야 할 방에서 빈 칩이 남는다.
  it("두 칩 모두 판정 결과로 가드되고 그 값을 이름으로 받는다", () => {
    for (const placement of ["header", "input-bar"]) {
      const guarded = guardedChips.filter((chip) => chip.includes(`placement="${placement}"`));
      expect(guarded).toHaveLength(1);
      expect(guarded[0]).toContain("modelName={chatModelChipLabel}");
    }
  });
});
