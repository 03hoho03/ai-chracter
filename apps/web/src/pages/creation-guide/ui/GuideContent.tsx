import type { GuideMockupContext } from "../model/guideMockupContext";
import type { GuideFieldBlock as GuideFieldBlockData, GuideItem, GuideNoteBlock, SectionContent } from "../model/parseManuscript";
import { GuideFieldBlock, GuideNoteBlockView } from "./GuideFieldBlock";
import { GuideItems } from "./GuideItems";
import type { GuideMarkdownProps } from "./GuideMarkdown";

type GuideContentProps = {
  content: readonly SectionContent[];
  /** 칸 블록을 그릴 때만 필요하다(칸 블록은 목업 표가 있는 토픽에만 있다). */
  mockupContext?: GuideMockupContext;
} & Pick<GuideMarkdownProps, "headingLevel" | "linkTone">;

/** 절 본문 — 산문 조각과 칸 블록·칸 아닌 블록을 원고 순서대로 그린다. */
export function GuideContent({ content, mockupContext, headingLevel, linkTone }: GuideContentProps) {
  return groupRuns(content).map((run, index) => {
    if (run.kind === "items") {
      // 원고에서 온 고정 목록이라 순서가 바뀌지 않아 위치를 key 로 쓴다.
      return <GuideItems key={index} items={run.items} headingLevel={headingLevel} linkTone={linkTone} />;
    }
    if (run.block.kind === "note") return <GuideNoteBlockView key={run.block.id} block={run.block} />;
    if (!mockupContext) throw new Error(`목업 표가 없는 토픽에 칸 블록이 있다: ${run.block.id}`);
    return <GuideFieldBlock key={run.block.id} block={run.block} context={mockupContext} />;
  });
}

type Run = { kind: "items"; items: GuideItem[] } | { kind: "block"; block: GuideFieldBlockData | GuideNoteBlock };

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
