import { TriangleAlert } from "lucide-react";
import { useFormContext, useWatch } from "react-hook-form";

import { findUnknownMediaTags, type MediaTagFieldPath, type StoryBuilderFormValues } from "@/features/build-story";

/** 태그가 그림이 되는 글에서, 그림이 없는 칸을 가리키는 태그를 알린다(화면에는 빈칸으로 남는다). */
export function UnknownMediaTagNotice({ name }: { name: MediaTagFieldPath }) {
  const { control } = useFormContext<StoryBuilderFormValues>();
  const text = useWatch({ control, name });
  const mediaBook = useWatch({ control, name: "mediaBook" });
  const unknown = findUnknownMediaTags(text, mediaBook);
  if (unknown.length === 0) return null;

  return (
    <p className="flex items-start gap-1.5 text-xs break-keep text-muted-foreground">
      <TriangleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
      <span>
        미디어 북에 이미지가 없는 칸이라 화면에는 빈칸으로 남아요:{" "}
        <span className="break-all text-foreground">{unknown.join(" ")}</span>
      </span>
    </p>
  );
}
