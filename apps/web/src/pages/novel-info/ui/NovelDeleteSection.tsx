import { Button } from "@ai-character-chat/ui/components/button";
import { Trash2 } from "lucide-react";
import { useId } from "react";

import type { NovelDetailResponse } from "@/entities/novel";
import { DeleteNovelModal } from "@/features/delete-novel";

/** 소설 지우기. 문서 끝, 다른 모든 것 아래에 둔다 — 되돌릴 수 없는 일이라 지나다 누를 자리에 두지 않는다. 실행
 * 버튼은 빨강 틴트다(솔리드 빨강은 이 시스템에 없다). 지운 뒤 작품 정보 화면에 있으면 모달이 내 소설로 보낸다. */
export function NovelDeleteSection({ novel }: { novel: NovelDetailResponse }) {
  const headingId = useId();

  return (
    <section aria-labelledby={headingId} className="flex flex-col items-start gap-2 border-t border-border pt-6">
      <h2 id={headingId} className="text-sm font-medium text-muted-foreground">
        소설 관리
      </h2>
      <p className="text-sm break-keep text-muted-foreground">
        지우면 모든 화와 판 이력, 설정 노트가 함께 사라져요. 원래 대화방은 그대로예요.
      </p>
      <Button
        type="button"
        variant="destructive"
        size="sm"
        onClick={() =>
          void DeleteNovelModal.call({
            novelId: novel.id,
            title: novel.title ?? novel.contentTitle,
            hasActiveJob: novel.activeJob !== null,
          })
        }
      >
        <Trash2 aria-hidden />
        소설 지우기
      </Button>
    </section>
  );
}
