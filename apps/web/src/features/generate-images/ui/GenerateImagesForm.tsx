import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ai-character-chat/ui/components/select";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";

import {
  IMAGE_ASPECT_RATIO_OPTIONS,
  IMAGE_COUNT_OPTIONS,
  IMAGE_STYLE_PRESET_OPTIONS,
  generateImagesDefaultValues,
  generateImagesSchema,
  type GenerateImagesFormValues,
} from "../model/schema";

interface GenerateImagesFormProps {
  onSubmit?: (values: GenerateImagesFormValues) => void | Promise<void>;
}

function noop() {
  // US-008이 잡 생성 + 폴링 로직을 이 자리에 주입한다.
}

export function GenerateImagesForm({ onSubmit = noop }: GenerateImagesFormProps) {
  const {
    register,
    handleSubmit,
    control,
    formState: { errors, isSubmitting },
  } = useForm<GenerateImagesFormValues>({
    resolver: zodResolver(generateImagesSchema),
    defaultValues: generateImagesDefaultValues,
  });

  return (
    <form
      className="flex flex-col gap-6"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit(onSubmit)(event);
      }}
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="generate-images-prompt">프롬프트</Label>
        <Textarea
          id="generate-images-prompt"
          placeholder="생성하고 싶은 이미지를 설명해주세요"
          rows={4}
          aria-invalid={!!errors.prompt}
          aria-describedby={errors.prompt ? "generate-images-prompt-error" : undefined}
          {...register("prompt")}
        />
        {errors.prompt && (
          <p id="generate-images-prompt-error" role="alert" className="text-xs text-destructive">
            {errors.prompt.message}
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="generate-images-style">스타일</Label>
          <Controller
            control={control}
            name="style"
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger id="generate-images-style" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {IMAGE_STYLE_PRESET_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="generate-images-aspect-ratio">비율</Label>
          <Controller
            control={control}
            name="aspectRatio"
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger id="generate-images-aspect-ratio" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {IMAGE_ASPECT_RATIO_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="generate-images-count">개수</Label>
          <Controller
            control={control}
            name="count"
            render={({ field }) => (
              <Select
                value={String(field.value)}
                onValueChange={(value) => field.onChange(Number(value))}
              >
                <SelectTrigger id="generate-images-count" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {IMAGE_COUNT_OPTIONS.map((count) => (
                    <SelectItem key={count} value={String(count)}>
                      {count}장
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        </div>
      </div>

      <Button type="submit" className="self-start" disabled={isSubmitting}>
        이미지 생성
      </Button>
    </form>
  );
}
