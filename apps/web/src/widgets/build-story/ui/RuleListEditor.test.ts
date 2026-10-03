import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { removeRuleListItem, type RuleListItemValues, type SingleRuleValues, type StatDefValues } from "@/features/build-story";

import { RuleListEditor } from "./RuleListEditor";

const KEPT: StatDefValues = {
  id: "kept",
  name: "호감도",
  icon: "Heart",
  color: "c",
  min: 0,
  max: 100,
  initial: 0,
  description: "d",
  perTurnDelta: null,
  changeDirection: "both",
  maxChangePerTurn: null,
};

function rule(id: string, statId: string): SingleRuleValues {
  return { kind: "rule", id, statId, operator: ">=", value: 50, nextOp: null };
}

function render(items: RuleListItemValues[], emptyText = "규칙이 없어요.") {
  return renderToStaticMarkup(
    createElement(RuleListEditor, {
      items,
      stats: [KEPT],
      allowGroups: true,
      emptyText,
      groupList: "ruleGroup",
      onChange: () => undefined,
    }),
  );
}

const MISSING_STAT_SENTENCE = "이 조건의 스탯이 지워졌어요. 다른 스탯을 고르거나 조건을 지워 주세요.";

describe("RuleListEditor 지워진 스탯 조건", () => {
  it("목록에 없는 스탯을 가리키는 조건은 스탯 칸에 '지워진 스탯'을 오류로 그리고 고치는 법을 잇는다", () => {
    const html = render([rule("r1", "gone")]);

    expect(html).toContain("지워진 스탯");
    expect(html).toContain('aria-label="스탯 선택: 지워진 스탯"');
    expect(html).toContain('aria-invalid="true"');
    expect(html).toContain(`id="rule-r1-missing-stat"`);
    expect(html).toContain(MISSING_STAT_SENTENCE);
  });

  it("그룹 안의 지워진 스탯 조건은 접힌 그룹 머리 줄에도 경고를 띄운다", () => {
    const html = render([{ kind: "group", id: "g1", nextOp: null, rules: [rule("r1", "gone")] }]);

    expect(html).toContain("입력 오류가 있어요");
  });

  it("다른 스탯을 고르거나 조건을 지우면 표시가 사라진다", () => {
    const items: RuleListItemValues[] = [rule("r1", "gone"), rule("r2", "kept")];

    // 셀렉트에서 스탯을 고르면 편집기가 그 조건의 statId 만 바꿔 넘긴다.
    const fixed = items.map((item) => (item.id === "r1" ? { ...item, statId: "kept" } : item));
    expect(render(fixed)).not.toContain(MISSING_STAT_SENTENCE);
    // 줄 삭제 버튼은 그 조건만 지운다.
    expect(render(removeRuleListItem(items, "r1"))).not.toContain(MISSING_STAT_SENTENCE);
  });

  it("있는 스탯을 가리키는 조건은 그 스탯 이름을 그리고 경고가 없다", () => {
    const html = render([rule("r1", "kept")]);

    expect(html).toContain('aria-label="스탯 선택"');
    expect(html).not.toContain("지워진 스탯");
  });

  it("빈 목록에서는 호출부가 준 문장을 그린다", () => {
    expect(render([], "등록된 규칙이 없어요. 비워두면 판단 프롬프트만으로 엔딩을 판정해요.")).toContain(
      "등록된 규칙이 없어요. 비워두면 판단 프롬프트만으로 엔딩을 판정해요.",
    );
  });
});
