import { DialogDescription } from "@ai-character-chat/ui/components/dialog";
import { SheetDescription } from "@ai-character-chat/ui/components/sheet";
import { Info } from "lucide-react";

type ChapterBoundaryDescriptionProps = {
  /** 다이얼로그·시트 중 어느 배치의 설명인가 — 설명 요소가 둘이 다르다. */
  layout: "dialog" | "sheet";
  description: string;
};

/** 화 범위 고르는 화면의 설명. 고르는 법 한 문장 아래에 만든 화의 마지막 답을 바꾸면 생기는 일을 한 줄 덧붙인다. 두 줄을
 * 설명 요소 안에 함께 두어 대화 상자의 설명(aria-describedby)으로 같이 읽히게 한다. */
export function ChapterBoundaryDescription({ layout, description }: ChapterBoundaryDescriptionProps) {
  const body = (
    <div className="flex flex-col gap-2 break-keep">
      <p>{description}</p>
      <ChapterEndChangeNotice />
    </div>
  );
  return layout === "dialog" ? (
    <DialogDescription asChild>{body}</DialogDescription>
  ) : (
    <SheetDescription asChild>{body}</SheetDescription>
  );
}

/** 화를 만든 뒤 그 화의 마지막 답을 바꾸면 생기는 일. 화의 범위는 끝 답으로 정해 두므로, 그 답을 다시 생성하면 새 답은 다음
 * 화의 첫머리가 되고, 방금 전 답변으로 돌리면 돌아온 답이 그 화 범위 안에 들어와 원문이 달라진다 — 어느 쪽이든 그 화는 다시
 * 만들 수 없다. 대화 화면에서는 알릴 자리가 없어(어느 답이 화의 끝인지 채팅 응답에 없다) 범위를 고르는 이 화면에서 미리
 * 말한다. */
function ChapterEndChangeNotice() {
  return (
    <p className="flex gap-2">
      <Info aria-hidden className="mt-1 size-3.5 shrink-0" />
      만든 화의 마지막 답을 다시 생성하거나 방금 전 답변으로 돌리면 그 화는 다시 만들 수 없어요. 다시 생성한 답은 다음 화에 담겨요.
    </p>
  );
}
