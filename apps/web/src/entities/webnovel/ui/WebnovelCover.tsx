import { cn } from "@ai-character-chat/ui/lib/utils";
import { BookOpen } from "lucide-react";

type WebnovelCoverProps = {
  /** 원작의 지금 썸네일. 원작자가 탈퇴했거나 썸네일이 없으면 없다 — 기본 표지를 그린다. */
  url: string | null;
  /** 폭(그 밖의 크기는 2:3 비가 정한다). */
  className?: string;
  /** 첫 화면 안의 표지면 바로 받는다. */
  isPriority?: boolean;
};

/** 노벨 표지 — 원작 썸네일을 2:3 으로 잘라 보인다(캐릭터 원작의 정사각 썸네일도 같은 비로 잘라 목록 줄 높이를
 * 고르게 한다). 웰은 그림이 오기 전에 자리를 잡는다. 테두리는 썸네일에만 두는 카드 그림과 같은 `foreground/10` 이고,
 * 웰 채움은 페이지 배경 위에서 보이는 `secondary` 다. */
export function WebnovelCover({ url, className, isPriority = false }: WebnovelCoverProps) {
  return (
    <div className={cn("aspect-story shrink-0 overflow-hidden rounded-xl border border-foreground/10 bg-secondary", className)}>
      {url === null ? (
        <div className="flex size-full items-center justify-center">
          <BookOpen aria-hidden className="size-6 text-muted-foreground" />
        </div>
      ) : (
        <img
          src={url}
          alt=""
          loading={isPriority ? "eager" : "lazy"}
          decoding="async"
          className="size-full object-cover"
        />
      )}
    </div>
  );
}
