import { useId } from "react";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ImageOff } from "lucide-react";

import {
  toThumbnailAspect,
  toThumbnailAspectClass,
  type ContentType,
  type HomeCurationItem,
} from "@/entities/content";

import { toHomeCurationHeading } from "../model/homeCuration";

type HomeCurationSectionProps = {
  item: HomeCurationItem;
  onOpen: (type: ContentType, id: string) => void;
};

/** 운영자가 그 유형에 걸어 둔 한 편. 필터 행 아래·그리드 바로 위에 놓인다.
 *
 * 카드 전체가 상세 모달을 여는 하나의 클릭 영역이다(안에 다른 버튼이 없다) — 바깥은 그리드의 `ContentCard`와 같은
 * `role="button"` div 이고, 껍데기(배경·보더·hover)가 없는 것도, 포커스 링·눌림 표시도 같다. 강조는 솔리드 버튼이
 * 아니라 크기와 배치로 만든다: 그림 옆에 제목과 한 줄 소개를 가로로 펼쳐 그리드 카드보다 말이 많다.
 *
 * 그림 폭 상한(`w-28`→`sm:w-32`, 최대 128px)은 썸네일 축소본의 해상도에서 왔다 — 긴 변 512px 라 스토리(2:3)는
 * 가로 341px, 레티나(2배)에서 CSS 170px 까지만 선명하다. 그보다 크게 그리면 흐려지고, 원본을 쓰면 첫 화면이
 * 무거워진다. 첫 화면 안에 있으므로 지연 로드하지 않지만(`eager`) 우선순위는 올리지 않는다 — 128px 그림은 대개
 * 그리드 카드보다 작아 LCP 요소가 아니고(실측: 네 조건 중 하나만), 높은 우선순위는 LCP 후보인 그리드 첫 카드에 둔다. */
export function HomeCurationSection({ item, onOpen }: HomeCurationSectionProps) {
  const id = useId();
  const headingId = `${id}-heading`;
  const nameId = `${id}-name`;
  const oneLinerId = `${id}-one-liner`;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h2 id={headingId} className="text-sm font-medium text-muted-foreground">
        {toHomeCurationHeading(item.type)}
      </h2>
      <div
        role="button"
        tabIndex={0}
        aria-labelledby={`${nameId} ${oneLinerId}`}
        onClick={() => onOpen(item.type, item.id)}
        onKeyDown={(event) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          onOpen(item.type, item.id);
        }}
        className="flex w-full max-w-xl cursor-pointer items-start gap-4 rounded-xl text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px"
      >
        <div
          className={cn(
            toThumbnailAspectClass(toThumbnailAspect(item.type)),
            "w-28 shrink-0 overflow-hidden rounded-xl border border-foreground/10 bg-secondary sm:w-32",
          )}
        >
          {item.thumbnailUrl ? (
            <img
              src={item.thumbnailUrl}
              alt=""
              loading="eager"
              decoding="async"
              className="size-full object-cover"
            />
          ) : (
            <div className="flex size-full items-center justify-center text-muted-foreground">
              <ImageOff aria-hidden />
            </div>
          )}
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <p id={nameId} className="line-clamp-2 break-keep break-words text-lg font-semibold text-foreground">
            {item.name}
          </p>
          <p id={oneLinerId} className="line-clamp-4 break-keep break-words text-sm text-muted-foreground">
            {item.oneLiner}
          </p>
        </div>
      </div>
    </section>
  );
}
