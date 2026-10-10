import { closestCenter, DndContext } from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Button, buttonVariants } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Camera, ImageOff, Loader2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { useFieldArray, useFormContext, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { MAX_SITUATIONAL_IMAGE_TRIGGER_LENGTH, registerSituationalImage } from "@/entities/content";
import type { CharacterBuilderFormValues, CharacterCollapsibleList } from "@/features/build-character";
import {
  FieldCharacterCount,
  CollapsibleItemCard,
  focusNeighborToggle,
  ItemDragHandle,
  ItemRemoveButton,
  itemOpenKey,
  useBuilderUiState,
  useLimitedTextField,
  useSortableList,
  useUndoableRemoval,
  type SortableHandleProps,
} from "@/features/build-common";
import { uploadAsset } from "@/shared/api/asset/uploadAsset";
import { MAX_SOURCE_BYTES } from "@/shared/lib/asset/resizeImage";
import { uploadAssetErrorMessage } from "@/shared/lib/asset/uploadAssetErrorMessage";
import { firstLine } from "@/shared/lib/text/firstLine";
import { BuilderTextarea } from "@/shared/ui/BuilderTextarea";
import { FOCUS_WITHIN_RING_CLASSNAME } from "@/shared/ui/focusWithinRing";

import { situationalImageAfterRelink, situationalImageRelinkAction } from "../model/situationalImageRelink";
import { situationalImageThumbUrl, type SavedSituationalImage } from "../model/situationalImageThumbUrl";

const SITUATIONAL_IMAGE_LIST: CharacterCollapsibleList = "situationalImage";
const MAX_FILE_MEGABYTES = MAX_SOURCE_BYTES / (1024 * 1024);
const DESCRIPTION_SNIPPET_LENGTH = 20;

type AdvancedTabProps = {
  ensureContentVersionId: () => Promise<string>;
  /** 마지막 저장(또는 조회) 응답의 상황별 이미지 — 저장된 그림의 썸네일 주소를 여기서 찾는다. 폼 값에는 주소를 넣지 않는다. */
  savedImages: readonly SavedSituationalImage[];
};

/** 탭 전체가 선택사항, 이미지+노출상황 쌍을 여러 개
 * 등록/조회/수정/삭제, dnd-kit 재정렬, 동시매칭 시 최상단 1개만 노출된다는 안내. */
export function AdvancedTab({ ensureContentVersionId, savedImages }: AdvancedTabProps) {
  const form = useFormContext<CharacterBuilderFormValues>();

  const { control, getValues, setValue } = form;
  const { fields, append, remove, move, insert } = useFieldArray({ control, name: "situationalImages" });
  const sortable = useSortableList({
    ids: fields.map((field) => field.id),
    move,
    itemObject: "상황별 이미지를",
    orderMeaning: "여러 이미지가 함께 맞으면 위에 있는 것이 보여요.",
  });
  const removeWithUndo = useUndoableRemoval({
    getItems: () => getValues("situationalImages"),
    remove,
    insert: (index, item) => {
      insert(index, item, { shouldFocus: false });
      if (item.image !== null) void relinkImage(item.id, item.image.assetId);
    },
    openKey: (id) => itemOpenKey(SITUATIONAL_IMAGE_LIST, id),
    objectPhrase: situationalImageObjectPhrase,
  });
  const uiState = useBuilderUiState();
  const addButtonRef = useRef<HTMLButtonElement>(null);
  // 상황이 비어 다시 등록하지 못한 되살린 그림 — 행 id 별 자산. 상황을 채우고 칸을 떠날 때 등록한다.
  const awaitingDescriptionRef = useRef(new Map<string, string>());

  // 상황을 채우지 않고 탭을 떠나면 서버 행에 그림이 없는 채로 남으므로 폼도 '이미지 없음'으로 맞춘다 — 남겨 두면 화면은
  // 등록됨인데 다시 열면 이미지 없음이 되고 발행이 거절된다.
  useEffect(() => {
    const awaiting = awaitingDescriptionRef.current;
    return () => {
      for (const [itemId, assetId] of awaiting) clearImageIfStill(itemId, assetId);
      awaiting.clear();
    };
  }, []);

  function clearImageIfStill(itemId: string, assetId: string) {
    const index = getValues("situationalImages").findIndex((item) => item.id === itemId);
    if (index !== -1 && getValues(`situationalImages.${index}.image`)?.assetId === assetId) {
      setValue(`situationalImages.${index}.image`, null, { shouldDirty: true });
    }
  }

  /**
   * 되살린 항목의 그림을 서버 행에 다시 잇는다. 서버는 저장 요청에 없는 행을 지우고, 같은 id 로 다시 오면 그림 없이 만든다 —
   * 그래서 지운 뒤 자동저장이 한 번 지나갔다면 폼만 되살려서는 그림이 사라진다. 등록은 같은 행에 덮어쓰므로 저장이 안 지나간
   * 경우에도 그대로 불러도 된다. 자산은 지워도 남아 있다.
   *
   * 등록 뒤에는 저장을 한 번 더 일으킨다. 되살린 뒤의 자동저장 응답이 등록보다 먼저 오면 초안 캐시에 그 행이 그림 없이
   * 남는다 — 썸네일이 글자로 머물고, 캐시가 살아 있는 동안 빌더를 다시 열면 폼이 그 캐시로 '이미지 없음'을 갖고 시작한다.
   */
  async function relinkImage(itemId: string, assetId: string) {
    awaitingDescriptionRef.current.delete(itemId);
    try {
      const contentVersionId = await ensureContentVersionId();
      const items = getValues("situationalImages");
      const index = items.findIndex((item) => item.id === itemId);
      const item = items[index];
      const action = situationalImageRelinkAction(assetId, item);
      if (action === "skip" || item === undefined) return;
      if (action === "wait-description") {
        awaitingDescriptionRef.current.set(itemId, assetId);
        toast("노출할 상황을 쓰면 되돌린 이미지가 다시 연결돼요.", { id: `situational-image-relink-${itemId}` });
        return;
      }
      await registerSituationalImage(assetId, {
        entityId: itemId,
        contentVersionId,
        triggerCondition: item.situationDescription,
        order: index,
      });
      const savedIndex = getValues("situationalImages").findIndex((row) => row.id === itemId);
      const currentImage = savedIndex === -1 ? undefined : getValues(`situationalImages.${savedIndex}.image`);
      const next = situationalImageAfterRelink(assetId, currentImage);
      // 폼 값은 그대로라(같은 값을 다시 넣으면 RHF 가 변경을 알리지 않아 자동저장이 안 돈다) 저장을 직접 부른다. 이 저장이
      // 실패해도 그림은 서버 행에 이어졌다 — 캐시만 다음 저장까지 낡으므로 등록 실패로 다루지 않는다.
      if (next === "save") void ensureContentVersionId().catch(() => undefined);
      if (next === "register-current" && currentImage) void relinkImage(itemId, currentImage.assetId);
    } catch {
      // 서버 행에 그림이 없으니 폼도 '이미지 없음'으로 맞춘다 — 남겨 두면 화면은 등록됨인데 발행이 거절된다.
      clearImageIfStill(itemId, assetId);
      toast.error("되돌린 상황별 이미지의 그림을 다시 붙이지 못했어요. 이미지를 다시 올려주세요.");
    }
  }

  /** 상황 칸을 떠날 때 — 상황이 비어 미뤄 둔 등록이 있으면 지금 한다. */
  function handleDescriptionBlur(itemId: string) {
    const assetId = awaitingDescriptionRef.current.get(itemId);
    if (assetId !== undefined) void relinkImage(itemId, assetId);
  }

  function handleAppend() {
    const id = crypto.randomUUID();
    // 새 항목을 열림으로 기록하는 일은 append 와 같은 핸들러에서 그보다 먼저 한다. 같은 커밋에 본문이 보여야 append 가
    // 주는 포커스가 숨은 입력칸에 걸려 헛돌지 않는다.
    uiState.open([itemOpenKey(SITUATIONAL_IMAGE_LIST, id)]);
    append(
      { id, image: null, situationDescription: "" },
      { focusName: `situationalImages.${fields.length}.situationDescription` },
    );
  }

  function handleRemove(index: number) {
    // 지우기 전에 포커스를 옮긴다 — 지운 뒤로 미루면 누른 삭제 버튼이 사라지며 포커스가 문서 맨 앞으로 떨어진다.
    const keys = getValues("situationalImages").map((image) => itemOpenKey(SITUATIONAL_IMAGE_LIST, image.id));
    focusNeighborToggle(keys, index, addButtonRef.current);
    removeWithUndo(index);
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
        <DndContext
          sensors={sortable.sensors}
          collisionDetection={closestCenter}
          onDragEnd={sortable.handleDragEnd}
          accessibility={sortable.accessibility}
        >
          <SortableContext items={fields.map((field) => field.id)} strategy={verticalListSortingStrategy}>
            <div className="flex flex-col gap-3">
              {fields.map((field, index) => (
                <SituationalImageRow
                  key={field.id}
                  id={field.id}
                  index={index}
                  savedImages={savedImages}
                  handleProps={sortable.handleProps(index)}
                  ensureContentVersionId={ensureContentVersionId}
                  onDescriptionBlur={handleDescriptionBlur}
                  onRemove={() => handleRemove(index)}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}

      <Button ref={addButtonRef} type="button" variant="secondary" className="w-fit" onClick={handleAppend}>
        상황별 이미지 추가
      </Button>

      <p className="sr-only" aria-live="polite">
        {sortable.announcement}
      </p>
    </div>
  );
}

/** 삭제 토스트 문장의 목적어 — 머리 줄에 보이는 상황 설명 첫 줄로 어느 항목인지 가른다. */
function situationalImageObjectPhrase(item: { situationDescription: string }): string {
  const characters = [...firstLine(item.situationDescription)];
  if (characters.length === 0) return "상황별 이미지를";
  const snippet =
    characters.length > DESCRIPTION_SNIPPET_LENGTH
      ? `${characters.slice(0, DESCRIPTION_SNIPPET_LENGTH).join("")}…`
      : characters.join("");
  return `‘${snippet}’ 상황별 이미지를`;
}

type SituationalImageRowProps = {
  id: string;
  index: number;
  savedImages: readonly SavedSituationalImage[];
  /** 손잡이의 id·화살표 키 재정렬(`useSortableList`). */
  handleProps: SortableHandleProps;
  ensureContentVersionId: () => Promise<string>;
  /** 상황 칸을 떠날 때(인자는 폼 값의 행 id). */
  onDescriptionBlur: (itemId: string) => void;
  onRemove: () => void;
};

/** 목록 순서가 곧 우선순위라 dnd-kit로 재정렬한다 — 순서가
 * 의미 없는 배열(IntroTab의 예시 대화)과 달리 add/remove만으로는 부족하다. 이미지는 업로드
 * 전용(AI 생성 진입점 없음)이라 GeneratedImageField(갤러리 선택 포함)를 재사용하지 않는다.
 * 업로드 완료 시 `PATCH /contents/{id}/draft`가 아니라 `POST /assets/{id}/register-situational-
 * image`로 즉시 등록해야 서버에 반영된다(apps/api CLAUDE.md, formToServer는 이 필드를 보내지
 * 않음) — 그래서 "노출 상황" 텍스트가 비어있으면(서버가 필수로 요구) 업로드를 막는다. 칸 순서도 설명 → 업로드로 두어
 * 위에서 아래로 채우면 막힐 일이 없게 하고, 막을 때는 파일 창을 열지 않고 사유를 보인다 — 파일을 고른 뒤에 막으면 고른
 * 파일이 버려진다. 막는 검사는 폼 검증이 아니라 값을 직접 본다(검증 오류를 세우면 선택 기능인 이 탭이 오류 탭으로 빨개진다).
 *
 * content_version_id를 값이 아니라 `ensureContentVersionId()`로 받는 이유는 초안 지연 생성이다 — 초안은 첫
 * 저장 시점에야 만들어지므로, 이 등록이 초안 생성을 먼저 트리거해야 한다.
 *
 * 접힌 머리 줄에는 이미지 상태를 꼭 보인다 — 이미지 없는 항목은 서버가 발행을 거절하는데 그 거절은 목록 전체만 가리켜,
 * 접힌 목록에서 어느 항목인지 찾을 단서가 이것뿐이다. 업로드 중에 접어도 본문을 언마운트하지 않아 진행 상태와 미리보기가
 * 남는다. 열림 키는 폼 값의 id 다(`id` prop 은 끌어 옮기기용 필드 배열 id 라 탭을 다시 열면 바뀐다). */
function SituationalImageRow({
  id,
  index,
  savedImages,
  handleProps,
  ensureContentVersionId,
  onDescriptionBlur,
  onRemove,
}: SituationalImageRowProps) {
  const form = useFormContext<CharacterBuilderFormValues>();

  const {
    getValues,
    setValue,
    control,
    formState: { errors },
  } = form;
  const situation = useLimitedTextField<CharacterBuilderFormValues>(
    `situationalImages.${index}.situationDescription`,
    MAX_SITUATIONAL_IMAGE_TRIGGER_LENGTH,
  );
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id });
  // 방금 올린 파일과 그 자산 — 미리보기는 폼 행이 아직 그 자산을 쥐고 있을 때만 쓴다.
  const [uploaded, setUploaded] = useState<{ assetId: string; file: File }>();
  const [isUploading, setIsUploading] = useState(false);
  const situationalImage = useWatch({ control, name: `situationalImages.${index}` });
  const hasRegisteredImage = situationalImage.image !== null;
  const isMissingDescription = situationalImage.situationDescription.trim() === "";
  const itemErrors = errors.situationalImages?.[index];
  const situationDescriptionError = itemErrors?.situationDescription;
  const situationDescriptionErrorId = `situational-image-${id}-description-error`;
  const situationDescriptionCountId = `situational-image-${id}-description-count`;
  const title = `상황별 이미지 ${index + 1}`;

  const objectPreviewUrl = useMemo(
    () => (uploaded ? URL.createObjectURL(uploaded.file) : undefined),
    [uploaded],
  );
  useEffect(() => {
    if (!objectPreviewUrl) return;
    return () => URL.revokeObjectURL(objectPreviewUrl);
  }, [objectPreviewUrl]);
  const thumbUrl = situationalImageThumbUrl({
    itemId: situationalImage.id,
    image: situationalImage.image,
    local: uploaded && objectPreviewUrl ? { assetId: uploaded.assetId, url: objectPreviewUrl } : undefined,
    saved: savedImages,
  });

  /** 기다리는 동안 목록이 재정렬·삭제·되돌리기로 바뀌었을 수 있어, 비동기 뒤에는 렌더 때의 `index` 대신 행 id 로 자리를 다시 찾는다. */
  function currentIndexOf(itemId: string): number {
    return getValues("situationalImages").findIndex((item) => item.id === itemId);
  }

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    const itemId = getValues(`situationalImages.${index}.id`);
    const triggerCondition = getValues(`situationalImages.${index}.situationDescription`);
    if (triggerCondition.trim() === "") return;

    setIsUploading(true);
    try {
      const contentVersionId = await ensureContentVersionId();
      const assetId = await uploadAsset(file, "situational-image");
      const order = currentIndexOf(itemId);
      // 올리는 동안 지운 항목이면 잇지 않는다 — 그 행은 다음 자동저장이 서버에서도 지운다.
      if (order === -1) return;
      await registerSituationalImage(assetId, { entityId: itemId, contentVersionId, triggerCondition, order });
      setUploaded({ assetId, file });
      const index = currentIndexOf(itemId);
      if (index !== -1) setValue(`situationalImages.${index}.image`, { assetId }, { shouldDirty: true });
    } catch (error) {
      toast.error(uploadAssetErrorMessage(error));
    } finally {
      setIsUploading(false);
    }
  }

  const inputId = `situational-image-upload-${id}`;
  const descriptionId = `situational-image-${id}-description`;
  const uploadHelpId = `situational-image-${id}-upload-help`;
  const uploadBlockedId = `situational-image-${id}-upload-blocked`;
  const isUploadBlocked = isUploading || isMissingDescription;
  const description = firstLine(situationalImage.situationDescription);

  return (
    <CollapsibleItemCard
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      openKey={itemOpenKey(SITUATIONAL_IMAGE_LIST, situationalImage.id)}
      title=""
      placeholderTitle={title}
      summary={[imageStatusLabel(isUploading, hasRegisteredImage), description].filter(Boolean).join(" · ")}
      hasError={!!itemErrors}
      leading={
        <ItemDragHandle
          {...attributes}
          {...listeners}
          {...handleProps}
          aria-label={`${index + 1}번째 상황별 이미지 순서 변경`}
        />
      }
      trailing={<ItemRemoveButton label={`${title} 삭제`} onClick={onRemove} />}
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={descriptionId}>노출할 상황</Label>
        <BuilderTextarea
          id={descriptionId}
          placeholder="어떤 상황에서 이 이미지를 노출할지 입력해주세요"
          rows={2}
          aria-invalid={!!situationDescriptionError}
          aria-describedby={
            situationDescriptionError
              ? `${situationDescriptionCountId} ${situationDescriptionErrorId}`
              : situationDescriptionCountId
          }
          {...situation.registration}
          onBlur={(event) => {
            void situation.registration.onBlur(event);
            onDescriptionBlur(situationalImage.id);
          }}
        />
        <FieldCharacterCount
          id={situationDescriptionCountId}
          name={situation.registration.name}
          max={MAX_SITUATIONAL_IMAGE_TRIGGER_LENGTH}
          isTruncated={situation.isTruncated}
        />
        {situationDescriptionError && (
          <p id={situationDescriptionErrorId} role="alert" className="text-xs text-destructive-text">
            {situationDescriptionError.message}
          </p>
        )}
      </div>

      <div className="flex items-start gap-3">
        <div className="relative size-16 shrink-0 overflow-hidden rounded-lg bg-muted">
          <SituationalImageThumb url={thumbUrl} hasRegisteredImage={hasRegisteredImage} />
          {isUploading && (
            <div className="absolute inset-0 flex items-center justify-center bg-background/70">
              <Loader2 aria-hidden className="size-4 animate-spin text-foreground" />
            </div>
          )}
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          {/* 머리 줄의 삭제 Button(variant="ghost" size="icon", 36px)과 하단 "상황별 이미지 추가"
              Button(variant="secondary" size="default", 36px)이 모두 36px라 default로 맞춘다.
              숫자를 손코딩하지 않고 buttonVariants로 치수를 위임해 다음 변경에 자동으로 따라가게 한다. */}
          <Label
            htmlFor={inputId}
            aria-disabled={isUploadBlocked}
            className={cn(
              buttonVariants({ variant: "outline", size: "default" }),
              "w-fit cursor-pointer aria-disabled:pointer-events-none aria-disabled:opacity-65",
              FOCUS_WITHIN_RING_CLASSNAME
            )}
          >
            <Camera aria-hidden className="size-4" />
            {isUploading ? "업로드 중..." : "파일 업로드"}
            <input
              id={inputId}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="sr-only"
              aria-disabled={isUploadBlocked}
              aria-describedby={isMissingDescription ? `${uploadBlockedId} ${uploadHelpId}` : uploadHelpId}
              // 막혔을 때는 파일 창을 열지 않는다. `disabled` 를 주면 이 입력에 있던 키보드 포커스가 body 로 떨어지고 사유도
              // 읽히지 않는다. 검사는 렌더 값이 아니라 지금 폼 값으로 한다.
              onClick={(event) => {
                if (isUploading || getValues(`situationalImages.${index}.situationDescription`).trim() === "") {
                  event.preventDefault();
                }
              }}
              onChange={(event) => void handleFileChange(event)}
            />
          </Label>
          {isMissingDescription && (
            <p id={uploadBlockedId} className="text-xs break-keep text-muted-foreground">
              노출할 상황을 먼저 쓰면 이미지를 올릴 수 있어요.
            </p>
          )}
          <p id={uploadHelpId} className="text-xs break-keep text-muted-foreground">
            PNG·JPG·WebP, 한 장에 {MAX_FILE_MEGABYTES}MB까지예요.
          </p>
        </div>
      </div>
    </CollapsibleItemCard>
  );
}

/** 접힌 머리 줄의 이미지 상태. 업로드가 끝나야 폼 값에 이미지가 들어가므로 진행 중은 따로 가른다. */
function imageStatusLabel(isUploading: boolean, hasRegisteredImage: boolean): string {
  if (isUploading) return "올리는 중";
  return hasRegisteredImage ? "등록됨" : "이미지 없음";
}

/** 세 갈래(그림 주소·주소 없이 등록만 된 이미지·없음)가 배타적이라 early return으로 편다. 주소 없이 등록된 경우는 주소를
 * 싣지 않는 옛 서버의 응답과, 지운 뒤 저장이 지나간 항목을 되살리고 다음 저장 응답이 오기 전까지의 짧은 구간이다. */
function SituationalImageThumb({ url, hasRegisteredImage }: { url: string | null; hasRegisteredImage: boolean }) {
  if (url !== null) {
    return (
      <img
        src={url}
        alt=""
        loading="lazy"
        decoding="async"
        className="size-full object-cover"
      />
    );
  }

  if (hasRegisteredImage) {
    return (
      <div className="flex size-full items-center justify-center text-center text-xs text-muted-foreground">
        등록됨
      </div>
    );
  }

  return (
      <div className="flex size-full items-center justify-center text-muted-foreground">
        <ImageOff aria-hidden />
      </div>
  );
}
