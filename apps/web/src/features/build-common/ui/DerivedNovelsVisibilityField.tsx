import { Label } from "@ai-character-chat/ui/components/label";
import { Switch } from "@ai-character-chat/ui/components/switch";
import { toast } from "sonner";

import { useContentDetailQuery, useUpdateDerivedNovelsVisibilityMutation } from "@/entities/content";

type DerivedNovelsVisibilityFieldProps = {
  /** 발행된 작품의 id — 값은 그 작품의 공개 상세 응답에서 읽는다(초안 응답에는 이 칸이 없다). */
  contentId: string;
  idPrefix: string;
};

/**
 * 공개 준비 탭 맨 아래의 "작품 상세에 이 작품으로 만든 공개 소설 보이기" 스위치. 발행작에서만 그린다 — 파생 소설은 발행작에서만 생기고,
 * 처음 값을 읽을 공개 상세 응답도 발행 뒤에만 있다. 끄면 원작 상세의 소설 목록만 숨기고 허락·소설의 공개는 그대로다.
 *
 * 값을 아직 못 읽었거나 읽지 못하면 줄을 그리지 않는다 — 기본값을 지어내 켜짐으로 보이면 이미 끈 작가에게 거짓말이 된다.
 */
export function DerivedNovelsVisibilityField({ contentId, idPrefix }: DerivedNovelsVisibilityFieldProps) {
  const detailQuery = useContentDetailQuery(contentId);
  const mutation = useUpdateDerivedNovelsVisibilityMutation(contentId);
  const visible = detailQuery.data?.derivedNovelsVisible;
  if (visible === undefined) return null;

  const switchId = `${idPrefix}-toggle`;
  const descriptionId = `${idPrefix}-description`;
  return (
    <div className="flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3">
      <div className="flex min-w-0 flex-col gap-0.5">
        <Label htmlFor={switchId} className="leading-snug break-keep">
          작품 상세에 이 작품으로 만든 공개 소설 보이기
        </Label>
        <p id={descriptionId} className="text-sm break-keep text-muted-foreground">
          끄면 작품 상세의 소설 목록만 숨겨요. 소설은 노벨에서 그대로 공개돼요.
        </p>
      </div>
      <Switch
        id={switchId}
        checked={visible}
        aria-describedby={descriptionId}
        onCheckedChange={(next) =>
          mutation.mutate(next, {
            onError: () => toast.error("설정을 바꾸지 못했어요. 잠시 후 다시 시도해주세요."),
          })
        }
      />
    </div>
  );
}
