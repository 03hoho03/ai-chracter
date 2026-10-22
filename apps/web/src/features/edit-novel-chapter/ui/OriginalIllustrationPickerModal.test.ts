// 원작 그림 고르기 창의 본문. 후보는 작가가 그 작품에서 본 그림(원작자 본인이면 지금 발행본의 그림 전부)이고, 원작을 열 수
// 없거나 본 그림이 없으면 서버가 빈 목록을 준다.
import { createElement, type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { OriginalIllustrationPickerBody } from "./OriginalIllustrationPickerModal";

function render(overrides: Partial<ComponentProps<typeof OriginalIllustrationPickerBody>>): string {
  return renderToStaticMarkup(
    createElement(OriginalIllustrationPickerBody, {
      isPending: false,
      isError: false,
      items: [],
      currentAssetId: undefined,
      onPick: () => {},
      ...overrides,
    }),
  );
}

describe("OriginalIllustrationPickerBody", () => {
  it("후보가 없으면 원작 방에서 본 그림이 여기 나온다고 말한다", () => {
    const markup = render({ items: [] });
    expect(markup).toContain("원작 방에서 본 그림이 여기 나와요.");
    expect(markup).toContain("아직 본 그림이 없어요.");
    expect(markup).not.toContain("<button");
  });

  it("후보마다 원작에서의 자리를 이름으로 단 버튼이 선다", () => {
    const markup = render({
      items: [
        { assetId: "a1", kind: "thumbnail", url: "https://img.example/a1.webp", width: 300, height: 400 },
        { assetId: "a2", kind: "situationalImage", url: "https://img.example/a2.webp", width: null, height: null },
        { assetId: "a3", kind: "mediaBook", url: "https://img.example/a3.webp", width: 400, height: 400 },
      ],
    });
    expect(markup).toContain('aria-label="대표 이미지 1"');
    expect(markup).toContain('aria-label="상황 이미지 2"');
    expect(markup).toContain('aria-label="미디어 북 이미지 3"');
    expect(markup).toContain("https://img.example/a2.webp");
  });

  // 바꾸기로 열었으면 지금 그 자리에 있는 그림을 표시해 같은 그림을 다시 고르는 일을 줄인다.
  it("바꾸려는 자리의 지금 그림에는 표식과 aria-current 가 있다", () => {
    const markup = render({
      items: [{ assetId: "a1", kind: "thumbnail", url: "https://img.example/a1.webp", width: 300, height: 400 }],
      currentAssetId: "a1",
    });
    expect(markup).toContain('aria-current="true"');
    expect(markup).toContain("지금 이미지");
  });

  it("불러오지 못했으면 다시 시도하라고 말한다", () => {
    expect(render({ isError: true })).toContain("불러오지 못했어요. 잠시 후 다시 시도해주세요.");
  });

  it("불러오는 중에는 격자 자리표시가 선다", () => {
    const markup = render({ isPending: true });
    expect(markup).toContain("animate-pulse");
    expect(markup).not.toContain("원작 방에서 본 그림이 여기 나와요.");
  });
});
