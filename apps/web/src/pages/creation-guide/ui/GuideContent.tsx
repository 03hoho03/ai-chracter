import { STORY_FIELD_LABELS } from "@/features/build-story";
import { assertNever } from "@/shared/lib/assertNever";

import { isStoryFieldKey } from "../model/mockupCaption";
import type { GuideFieldBlock, GuideItem, GuideNoteBlock, SectionContent } from "../model/parseManuscript";
import { type GuideDisplayItem, toDisplayItems } from "../model/toGuidePages";
import { GuideConversation } from "./GuideConversation";
import { GuideFieldExample } from "./GuideFieldExample";
import { GuideMarkdown } from "./GuideMarkdown";

// 임시 렌더러 — 라우트와 원고 모델이 맞물리는지만 보이는 최소 마크업이다. 칸 목업·좋은/나쁜 예·접기 모양은 디자인
// 작업에서 이 파일을 갈아 끼운다.

type GuideContentProps = {
  content: readonly SectionContent[];
};

export function GuideContent({ content }: GuideContentProps) {
  return groupRuns(content).map((run, index) => {
    // 원고에서 온 고정 목록이라 순서가 바뀌지 않아 위치를 key 로 쓴다.
    if (run.kind === "items") return <GuideItems key={index} items={run.items} />;
    if (run.block.kind === "field") return <GuideFieldBlockView key={run.block.id} block={run.block} />;
    return <GuideNoteBlockView key={run.block.id} block={run.block} />;
  });
}

type Run = { kind: "items"; items: GuideItem[] } | { kind: "block"; block: GuideFieldBlock | GuideNoteBlock };

/** 연달은 산문·예시 조각을 한 묶음으로 — 채팅 예시가 대화 한 판으로 묶이려면 같은 목록 안에 있어야 한다. */
function groupRuns(content: readonly SectionContent[]): Run[] {
  const runs: Run[] = [];
  for (const item of content) {
    if (item.kind === "field" || item.kind === "note") {
      runs.push({ kind: "block", block: item });
      continue;
    }
    const last = runs.at(-1);
    if (last?.kind === "items") last.items.push(item);
    else runs.push({ kind: "items", items: [item] });
  }
  return runs;
}

export function GuideItems({ items }: { items: readonly GuideItem[] }) {
  return toDisplayItems(items).map((item, index) => <GuideDisplayItemView key={index} item={item} />);
}

function GuideDisplayItemView({ item }: { item: GuideDisplayItem }) {
  switch (item.kind) {
    case "markdown":
      return <GuideMarkdown source={item.source} />;
    case "conversation":
      return <GuideConversation messages={item.messages} />;
    case "field":
      return <GuideFieldExample body={item.body} />;
    default:
      return assertNever(item);
  }
}

function GuideFieldBlockView({ block }: { block: GuideFieldBlock }) {
  const [firstKey = ""] = block.keys;
  const title = block.title ?? (isStoryFieldKey(firstKey) ? STORY_FIELD_LABELS[firstKey].label : firstKey);
  return (
    <section id={block.id} className="flex scroll-mt-20 flex-col gap-3">
      <h2 className="text-lg font-semibold text-foreground">{title}</h2>
      <GuideItems items={block.intro} />
      {block.values.map((value) => (
        <GuideFieldExample key={value.key} body={value.body} />
      ))}
      {block.details && (
        <details>
          <summary>자세히</summary>
          <GuideItems items={block.details} />
        </details>
      )}
      {block.bad.map((part) => (
        <details key={part.title}>
          <summary>나쁜 예 · {part.title}</summary>
          <GuideItems items={part.prose} />
          {part.good && <GuideFieldExample body={part.good.body} />}
          {part.values.map((value) => (
            <GuideFieldExample key={value.key} body={value.body} />
          ))}
        </details>
      ))}
    </section>
  );
}

function GuideNoteBlockView({ block }: { block: GuideNoteBlock }) {
  return (
    <section id={block.id} className="flex scroll-mt-20 flex-col gap-3">
      <h2 className="text-lg font-semibold text-foreground">{block.title}</h2>
      <GuideItems items={block.intro} />
      {block.details && (
        <details>
          <summary>자세히</summary>
          <GuideItems items={block.details} />
        </details>
      )}
    </section>
  );
}
