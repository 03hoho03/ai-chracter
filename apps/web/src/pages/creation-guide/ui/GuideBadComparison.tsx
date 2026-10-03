import { cn } from "@ai-character-chat/ui/lib/utils";
import { Ban, Check } from "lucide-react";

import { ChatMarkdown, USER_MESSAGE_FRAME } from "@/entities/chat-room";
import { assertNever } from "@/shared/lib/assertNever";

import type { GuideMockupContext } from "../model/guideMockupContext";
import type { FieldBadPart } from "../model/parseManuscript";
import { toDisplayItems } from "../model/toGuidePages";
import { GuideFieldMockups } from "./GuideFieldMockup";
import { GuideMarkdown } from "./GuideMarkdown";

type GuideBadComparisonProps = {
  part: FieldBadPart;
  context: GuideMockupContext;
  /** 한 칸에 나쁜 예가 둘 이상이면 접기 줄이 이름을 다 싣지 못해, 대비마다 이름을 위에 적는다. */
  showsTitle: boolean;
};

/**
 * 좋은 예 / 나쁜 예 한 벌. 색으로 가르지 않는다 — 초록·빨강을 칠하면 이 시스템의 유채색 규칙(강조와 사용자 콘텐츠,
 * 위험 틴트에만 색)을 어기고, 색을 구별하지 못하면 둘이 같아 보인다. 대신 아이콘(체크 / 금지)·글자 라벨·면의 명도 한 칸
 * (좋은 쪽은 바탕 윤곽, 나쁜 쪽은 `muted` 채움)으로 가른다. 회색조로 봐도 셋이 다 남는다.
 *
 * 좁은 화면은 위아래, 넓은 화면은 나란히 놓는다 — 비교는 동시에 보여야 한다. 좋은 쪽이 없는 대비(시드에 맞대어 보일 줄이
 * 없는 실수)는 나쁜 쪽만 오른쪽 칸에 둬, 좋은 쪽은 위의 칸 그림이라는 자리 관계를 지킨다.
 */
export function GuideBadComparison({ part, context, showsTitle }: GuideBadComparisonProps) {
  return (
    <div className="flex flex-col gap-2">
      {showsTitle && <p className="m-0 text-sm font-semibold text-foreground">{part.title}</p>}
      <div className="grid gap-3 lg:grid-cols-2 lg:items-start">
        {part.good && (
          <ComparisonSide tone="good">
            <GuideFieldMockups values={[part.good]} context={context} clampsLongText={false} />
          </ComparisonSide>
        )}
        <ComparisonSide tone="bad" className={cn(!part.good && "lg:col-start-2")}>
          {part.values.length > 0 && <GuideFieldMockups values={part.values} context={context} clampsLongText={false} />}
          <BadProse part={part} />
        </ComparisonSide>
      </div>
    </div>
  );
}

type ComparisonSideProps = {
  tone: "good" | "bad";
  className?: string;
  children: React.ReactNode;
};

function ComparisonSide({ tone, className, children }: ComparisonSideProps) {
  const isGood = tone === "good";
  const Icon = isGood ? Check : Ban;
  return (
    <figure
      className={cn(
        "m-0 flex min-w-0 cursor-default flex-col gap-3 rounded-xl border border-border p-3",
        isGood ? "bg-background" : "bg-muted",
        className,
      )}
    >
      <figcaption className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
        <Icon aria-hidden className="size-4 shrink-0" />
        {isGood ? "이렇게 써요" : "이렇게 쓰면"}
      </figcaption>
      {children}
    </figure>
  );
}

/**
 * 나쁜 쪽의 글 — 칸에 넣은 원문 예시, 그래서 생기는 일(설명 문단), 대화에 드러나는 증상(채팅). 원문 예시를 설명보다
 * 앞에 둔다: 읽는 사람이 "이렇게 쓰면" 바로 아래에서 먼저 쓴 글을 보고, 그다음에 결과를 읽게.
 */
function BadProse({ part }: { part: FieldBadPart }) {
  const items = toDisplayItems(part.prose);
  const ordered = [...items.filter((item) => item.kind === "field"), ...items.filter((item) => item.kind !== "field")];
  return ordered.map((item, index) => {
    // 원고에서 온 고정 목록이라 순서가 바뀌지 않는다.
    switch (item.kind) {
      case "field":
        return (
          <div
            key={index}
            className="rounded-lg border border-input px-3 py-2 text-sm leading-6 whitespace-pre-wrap break-keep wrap-break-word text-foreground"
          >
            {item.body}
          </div>
        );
      case "markdown":
        return <GuideMarkdown key={index} source={item.source} />;
      case "conversation":
        // 증상 채팅은 카드 없이 이 면에 바로 그린다. 상태창 코드 블록은 `muted` 면 위에서 사라지지 않게 `secondary` 다.
        return (
          <div key={index} className="flex flex-col gap-6">
            {item.messages.map((message, messageIndex) => (
              <div key={messageIndex} className={message.role === "user" ? USER_MESSAGE_FRAME : undefined}>
                <ChatMarkdown content={message.body} codeBlockSurface="secondary" />
              </div>
            ))}
          </div>
        );
      default:
        return assertNever(item);
    }
  });
}
