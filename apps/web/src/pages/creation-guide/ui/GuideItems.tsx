import { assertNever } from "@/shared/lib/assertNever";

import type { GuideItem } from "../model/parseManuscript";
import { toDisplayItems } from "../model/toGuidePages";
import { GuideConversation } from "./GuideConversation";
import { GuideFieldExample } from "./GuideFieldExample";
import { GuideMarkdown, type GuideMarkdownProps } from "./GuideMarkdown";

type GuideItemsProps = {
  items: readonly GuideItem[];
} & Pick<GuideMarkdownProps, "headingLevel" | "linkTone">;

/** 원고의 산문·예시 조각. 연달은 채팅 예시는 대화 한 판으로 묶어 그린다. */
export function GuideItems({ items, headingLevel, linkTone }: GuideItemsProps) {
  return toDisplayItems(items).map((item, index) => {
    // 원고에서 온 고정 목록이라 순서가 바뀌지 않아 위치를 key 로 쓴다.
    switch (item.kind) {
      case "markdown":
        return <GuideMarkdown key={index} source={item.source} headingLevel={headingLevel} linkTone={linkTone} />;
      case "conversation":
        return <GuideConversation key={index} messages={item.messages} />;
      case "field":
        return <GuideFieldExample key={index} body={item.body} />;
      default:
        return assertNever(item);
    }
  });
}
