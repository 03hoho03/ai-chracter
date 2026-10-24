// 대화로 바로 만드는 화(옛 흐름)의 화 범위 고르는 창 설명. 이 창은 운영 화면이라, 구성안으로 쓴 화의 안내를 따로 두어도 이 창의
// 글과 마크업은 글자 하나까지 같아야 한다. 설명 요소는 대화 상자 루트의 문맥만 읽어 포털 없이 서버 렌더에 나온다.
import { Dialog } from "@ai-character-chat/ui/components/dialog";
import { Sheet } from "@ai-character-chat/ui/components/sheet";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ChapterBoundaryDescription } from "./ChapterBoundaryDescription";

const DESCRIPTION = "이 화에 담을 마지막 턴을 고르세요.";

describe("옛 흐름 화 범위 고르는 창의 설명", () => {
  it("다이얼로그 배치", () => {
    const html = renderToStaticMarkup(
      createElement(Dialog, { open: true }, createElement(ChapterBoundaryDescription, { layout: "dialog", description: DESCRIPTION })),
    );
    expect(html).toMatchSnapshot();
  });

  it("시트 배치", () => {
    const html = renderToStaticMarkup(
      createElement(Sheet, { open: true }, createElement(ChapterBoundaryDescription, { layout: "sheet", description: DESCRIPTION })),
    );
    expect(html).toMatchSnapshot();
  });

  it("다시 생성한 답이 다음 화에 담긴다는 옛 흐름 안내를 그대로 말한다", () => {
    const html = renderToStaticMarkup(
      createElement(Dialog, { open: true }, createElement(ChapterBoundaryDescription, { layout: "dialog", description: DESCRIPTION })),
    );
    expect(html).toContain(
      "만든 화의 마지막 답을 다시 생성하거나 방금 전 답변으로 돌리면 그 화는 다시 만들 수 없어요. 다시 생성한 답은 다음 화에 담겨요.",
    );
  });
});
