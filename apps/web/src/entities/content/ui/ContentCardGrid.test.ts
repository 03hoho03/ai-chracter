// 공용 그리드의 열 클래스는 컨테이너 쿼리라 `@container` 조상이 없으면 하나도 켜지지 않는다 — 모든 폭에서 첫 단계
// (2열·3열)에 머문다. 그 조상은 이 컴포넌트가 직접 두는 래퍼라, 래퍼가 빠지거나 열 클래스가 래퍼로 올라가는 것을 잡는다.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { toGridColumns } from "./cardLayoutClass";
import { ContentCardGrid } from "./ContentCardGrid";

describe("ContentCardGrid", () => {
  it("wraps the column grid in a container so the width queries have something to measure", () => {
    const html = renderToStaticMarkup(
      createElement(ContentCardGrid, { thumbnailAspect: "portrait", tabIndex: -1, className: "outline-none", children: "카드" }),
    );
    expect(html).toBe(
      `<div class="@container w-full"><div tabindex="-1" class="grid gap-3 ${toGridColumns("portrait")} outline-none">카드</div></div>`,
    );
  });
});
