import { useState } from "react";
import { cn } from "@ai-character-chat/ui/lib/utils";

import type { CommentSticker } from "../model/comment";

export function CommentStickerImage({ sticker, className }: { sticker: CommentSticker; className?: string }) {
  const [failedUrl, setFailedUrl] = useState<string>();
  return (
    <span className={cn("inline-flex aspect-square w-32 max-w-full shrink-0 items-center justify-center", className)}>
      {failedUrl === sticker.imageUrl ? (
        <span role="img" aria-label={sticker.alt} className="break-keep text-center text-xs text-muted-foreground">
          {sticker.name} · 이미지를 불러오지 못했어요
        </span>
      ) : (
        <img src={sticker.imageUrl} alt={sticker.alt} width={256} height={256}
          loading="lazy" decoding="async" className="size-full object-contain"
          onError={() => setFailedUrl(sticker.imageUrl)} />
      )}
    </span>
  );
}
