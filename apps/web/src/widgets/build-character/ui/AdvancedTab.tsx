import {
  closestCenter,
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { Camera, GripVertical, ImageOff, Loader2, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState, type ChangeEvent } from "react";
import { useFieldArray, type UseFormReturn } from "react-hook-form";
import { toast } from "sonner";

import type { CharacterBuilderFormValues } from "../../../features/build-character";
import { registerSituationalImage } from "../../../shared/lib/asset/registerSituationalImage";
import { uploadAsset } from "../../../shared/lib/asset/uploadAsset";
import { uploadAssetErrorMessage } from "../../../shared/lib/asset/uploadAssetErrorMessage";

/** 목록 순서가 곧 우선순위(techspec-builder-character.md §2)라 dnd-kit로 재정렬한다 — 순서가
 * 의미 없는 배열(IntroTab의 예시 대화)과 달리 add/remove만으로는 부족하다. 이미지는 업로드
 * 전용(AI 생성 진입점 없음, §3)이라 GeneratedImageField(갤러리 선택 포함)를 재사용하지 않는다.
 * 업로드 완료 시 `PATCH /contents/{id}/draft`가 아니라 `POST /assets/{id}/register-situational-
 * image`로 즉시 등록해야 서버에 반영된다(apps/api CLAUDE.md, formToServer는 이 필드를 보내지
 * 않음) — 그래서 "노출 상황" 텍스트가 비어있으면(서버가 필수로 요구) 업로드를 막는다. */
function SituationalImageRow({
  id,
  index,
  form,
  contentVersionId,
  onRemove,
}: {
  id: string;
  index: number;
  form: UseFormReturn<CharacterBuilderFormValues>;
  contentVersionId: string;
  onRemove: () => void;
}) {
  const { register, getValues, setValue, watch } = form;
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id });
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const hasRegisteredImage = watch(`situationalImages.${index}.image`) !== null;

  const objectPreviewUrl = useMemo(
    () => (selectedFile ? URL.createObjectURL(selectedFile) : null),
    [selectedFile],
  );
  useEffect(() => {
    if (!objectPreviewUrl) return;
    return () => URL.revokeObjectURL(objectPreviewUrl);
  }, [objectPreviewUrl]);

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    const triggerCondition = getValues(`situationalImages.${index}.situationDescription`);
    if (!triggerCondition.trim()) {
      toast.error("노출 상황을 먼저 입력해주세요.");
      return;
    }

    setIsUploading(true);
    try {
      const assetId = await uploadAsset(file, "situational-image");
      await registerSituationalImage(assetId, {
        entityId: getValues(`situationalImages.${index}.id`),
        contentVersionId,
        triggerCondition,
        order: index,
      });
      setSelectedFile(file);
      setValue(`situationalImages.${index}.image`, { assetId }, { shouldDirty: true });
    } catch (error) {
      toast.error(uploadAssetErrorMessage(error));
    } finally {
      setIsUploading(false);
    }
  }

  const inputId = `situational-image-upload-${id}`;

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className="flex items-start gap-3 rounded-xl border border-border bg-background p-4"
    >
      <button
        type="button"
        aria-label="순서 변경"
        className="mt-1.5 cursor-grab touch-none text-muted-foreground hover:text-foreground focus-visible:outline-none"
        {...attributes}
        {...listeners}
      >
        <GripVertical aria-hidden />
      </button>

      <div className="relative size-16 shrink-0 overflow-hidden rounded-lg bg-muted">
        {objectPreviewUrl ? (
          <img
            src={objectPreviewUrl}
            alt=""
            loading="lazy"
            decoding="async"
            className="size-full object-cover"
          />
        ) : hasRegisteredImage ? (
          <div className="flex size-full items-center justify-center text-center text-xs text-muted-foreground">
            등록됨
          </div>
        ) : (
          <div className="flex size-full items-center justify-center text-muted-foreground">
            <ImageOff aria-hidden />
          </div>
        )}
        {isUploading && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/70">
            <Loader2 aria-hidden className="size-4 animate-spin text-foreground" />
          </div>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-2">
        <Label
          htmlFor={inputId}
          className="inline-flex h-8 w-fit cursor-pointer items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 text-sm font-medium hover:bg-muted has-disabled:pointer-events-none has-disabled:opacity-50"
        >
          <Camera aria-hidden className="size-4" />
          {isUploading ? "업로드 중..." : "파일 업로드"}
          <input
            id={inputId}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="sr-only"
            disabled={isUploading}
            onChange={(event) => void handleFileChange(event)}
          />
        </Label>
        <Textarea
          placeholder="어떤 상황에서 이 이미지를 노출할지 입력해주세요"
          rows={2}
          {...register(`situationalImages.${index}.situationDescription`)}
        />
      </div>

      <Button type="button" variant="ghost" size="icon" aria-label="상황별 이미지 삭제" onClick={onRemove}>
        <Trash2 aria-hidden />
      </Button>
    </div>
  );
}

/** techspec-builder-character.md §2 AC — 탭 전체가 선택사항, 이미지+노출상황 쌍을 여러 개
 * 등록/조회/수정/삭제, dnd-kit 재정렬, 동시매칭 시 최상단 1개만 노출된다는 안내. */
export function AdvancedTab({
  form,
  contentVersionId,
}: {
  form: UseFormReturn<CharacterBuilderFormValues>;
  contentVersionId: string;
}) {
  const { control } = form;
  const { fields, append, remove, move } = useFieldArray({ control, name: "situationalImages" });
  const sensors = useSensors(useSensor(PointerSensor));

  function handleDragEnd({ active, over }: DragEndEvent) {
    if (!over || active.id === over.id) return;
    const oldIndex = fields.findIndex((field) => field.id === active.id);
    const newIndex = fields.findIndex((field) => field.id === over.id);
    if (oldIndex !== -1 && newIndex !== -1) move(oldIndex, newIndex);
  }

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-1">
        <Label>상황별 이미지 (선택)</Label>
        <p className="text-sm text-muted-foreground">
          특정 대화 상황에서 노출할 이미지를 등록해요. 여러 이미지가 동시에 조건을 만족하면
          목록에서 가장 위에 있는 항목 하나만 노출돼요.
        </p>
      </div>

      {fields.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-10 text-center">
          <p className="text-sm text-muted-foreground">아직 등록된 상황별 이미지가 없어요.</p>
        </div>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={fields.map((field) => field.id)} strategy={verticalListSortingStrategy}>
            <div className="flex flex-col gap-3">
              {fields.map((field, index) => (
                <SituationalImageRow
                  key={field.id}
                  id={field.id}
                  index={index}
                  form={form}
                  contentVersionId={contentVersionId}
                  onRemove={() => remove(index)}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}

      <Button
        type="button"
        variant="secondary"
        className="w-fit"
        onClick={() => append({ id: crypto.randomUUID(), image: null, situationDescription: "" })}
      >
        상황별 이미지 추가
      </Button>
    </div>
  );
}
