import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { EpisodeRowList } from "./EpisodeRowList";

function render() {
  return renderToStaticMarkup(
    createElement(EpisodeRowList, {
      rows: [
        { key: "k1", ordinal: 3, title: "낯선 아침", sceneOutline: "approved", manuscript: { kind: "written", chapterId: "c3" } },
        { key: "k2", ordinal: 4, title: "금지된 탑", sceneOutline: "draft", manuscript: { kind: "next" } },
        { key: "k3", ordinal: 5, title: "", sceneOutline: "none", manuscript: { kind: "waiting" } },
        { key: "k4", ordinal: 6, title: "끝", sceneOutline: "stale", manuscript: { kind: "laterWritten" } },
      ],
      onOpenEpisode: () => {},
      onOpenChapter: () => {},
    }),
  );
}

describe("화별 장면·원고 목록", () => {
  const html = render();

  it("화마다 번호·제목과 장면 구성안·원고 상태를 단다", () => {
    expect(html).toContain("3화");
    expect(html).toContain("낯선 아침");
    expect(html).toContain("제목 없음");
    for (const label of ["장면 구성안 승인됨", "장면 구성안 초안", "장면 구성안 없음", "장면 구성안 낡음"]) {
      expect(html).toContain(label);
    }
    for (const label of ["원고 있음", "쓸 차례", "앞 화 먼저", "뒤 화에 원고 있음"]) {
      expect(html).toContain(label);
    }
  });

  it("화마다 열기 버튼이 이름을 갖고, 원고 있는 화에는 그 화로 가는 버튼이 있다", () => {
    expect(html).toContain('aria-label="4화 장면·원고 열기"');
    expect(html).toContain("3화 보기");
    expect(html).not.toContain("4화 보기");
  });
});
