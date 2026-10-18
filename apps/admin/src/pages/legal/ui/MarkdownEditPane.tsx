import { Markdown } from "@ai-character-chat/ui/components/markdown";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useState } from "react";

/** 좁은 화면에서는 고른 탭만 보이고, `lg` 이상에서는 두 패널이 늘 함께 보인다. */
const PANE_CLASS = "data-[state=inactive]:hidden lg:data-[state=inactive]:block";

const HEIGHT_CLASS = {
  // 약관 본문은 6천~1만2천 자라 높이에 캡을 씌워 패널 안에서 스크롤한다(안 그러면 Textarea 의 `field-sizing-content` 가
  // 본문 길이만큼 늘어나 페이지가 지나치게 길어진다).
  tall: "max-h-128 min-h-128",
  short: "max-h-72 min-h-48",
} as const;

type MarkdownEditPaneProps = {
  value: string;
  onChange: (next: string) => void;
  /** 편집칸의 접근 이름. */
  label: string;
  placeholder: string;
  height: keyof typeof HEIGHT_CLASS;
};

/** 넓은 화면(`lg` 이상)에서는 편집(좌)/미리보기(우)를 나란히 둔다 — 동시에 비교하는 편이 낫다. 그보다 좁으면 반 폭 두 칸이
 * 한 줄에 몇 글자 못 담아 둘 다 읽기 어렵고, 위아래로 쌓으면 미리보기가 편집기 아래로 밀려 안 보이므로 편집/미리보기 탭으로
 * 바꾼다. 두 패널은 늘 마운트돼 있다(탭은 숨기기만 한다) — 폭을 넘나들어도 편집기의 커서·스크롤이 남는다. */
export function MarkdownEditPane({ value, onChange, label, placeholder, height }: MarkdownEditPaneProps) {
  const [pane, setPane] = useState<"edit" | "preview">("edit");
  const heightClass = HEIGHT_CLASS[height];

  return (
    <Tabs
      value={pane}
      onValueChange={(next) => {
        if (next === "edit" || next === "preview") setPane(next);
      }}
      className="gap-3"
    >
      {/* 위의 문서 종류 탭(밑줄)과 층이 다르다는 걸 모양으로 가른다. */}
      <TabsList className="lg:hidden">
        <TabsTrigger value="edit">편집</TabsTrigger>
        <TabsTrigger value="preview">미리보기</TabsTrigger>
      </TabsList>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Radix 탭 패널은 Tab 정지(`tabIndex=0`)인데 편집 패널은 진입점이 곧 안의 편집칸이라 정지를 뺀다 — 남기면
            포커스가 보이지 않는 칸에 한 번 앉았다가 다음 Tab 에야 편집칸에 닿는다. */}
        <TabsContent value="edit" forceMount tabIndex={-1} className={PANE_CLASS}>
          <Textarea
            value={value}
            onChange={(event) => onChange(event.target.value)}
            placeholder={placeholder}
            aria-label={label}
            className={cn(heightClass, "resize-none overflow-y-auto")}
          />
        </TabsContent>
        <TabsContent
          value="preview"
          forceMount
          // 미리보기는 긴 본문을 키보드로 스크롤하는 Tab 정지로 남긴다 — 그래서 하우스 포커스 표시(불투명 보더 + 50% 링)를 준다.
          className={cn(
            PANE_CLASS,
            heightClass,
            "overflow-y-auto rounded-lg border border-border bg-card p-4 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
          )}
        >
          {value.trim() ? (
            <Markdown content={value} className="[&_code]:bg-secondary" />
          ) : (
            <p className="text-sm text-muted-foreground">미리볼 내용이 없어요.</p>
          )}
        </TabsContent>
      </div>
    </Tabs>
  );
}
