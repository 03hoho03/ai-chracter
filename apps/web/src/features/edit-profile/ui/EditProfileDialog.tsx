import { useEffect, useMemo, useState, type ChangeEvent } from "react";
import type { ApiError } from "@ai-character-chat/api-types";
import { Avatar, AvatarFallback, AvatarImage } from "@ai-character-chat/ui/components/avatar";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@ai-character-chat/ui/components/dialog";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { Camera, Pencil } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import type { UserProfileResponse } from "@/entities/profile";
import { uploadAsset } from "@/shared/lib/asset/uploadAsset";
import { uploadAssetErrorMessage } from "@/shared/lib/asset/uploadAssetErrorMessage";
import { useUpdateProfileMutation } from "../api/mutations";
import { editProfileDefaultValues, editProfileSchema, type EditProfileFormValues } from "../model/schema";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

export function EditProfileDialog({
  userId,
  profile,
}: {
  userId: string;
  profile: UserProfileResponse;
}) {
  const [open, setOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [profileImageAssetId, setProfileImageAssetId] = useState(profile.profileImageAssetId);
  const [isUploadingImage, setIsUploadingImage] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const form = useForm<EditProfileFormValues>({
    resolver: zodResolver(editProfileSchema),
    defaultValues: editProfileDefaultValues(profile),
  });

  const updateProfileMutation = useUpdateProfileMutation(userId);

  const previewUrl = useMemo(
    () => (selectedFile ? URL.createObjectURL(selectedFile) : null),
    [selectedFile],
  );
  useEffect(() => {
    if (!previewUrl) return;
    return () => URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  function handleOpenChange(nextOpen: boolean) {
    setOpen(nextOpen);
    if (nextOpen) {
      form.reset(editProfileDefaultValues(profile));
      setSelectedFile(null);
      setProfileImageAssetId(profile.profileImageAssetId);
      setFormError(null);
    }
  }

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    setSelectedFile(file);
    setIsUploadingImage(true);
    try {
      const assetId = await uploadAsset(file, "profile-image");
      setProfileImageAssetId(assetId);
    } catch (error) {
      toast.error(uploadAssetErrorMessage(error));
      setSelectedFile(null);
    } finally {
      setIsUploadingImage(false);
    }
  }

  async function onSubmit(values: EditProfileFormValues) {
    setFormError(null);
    try {
      await updateProfileMutation.mutateAsync({
        nickname: values.nickname,
        bio: values.bio.trim() === "" ? null : values.bio,
        profileImageAssetId,
      });
      toast.success("프로필이 저장되었어요.");
      setOpen(false);
    } catch (error) {
      const apiError = error as ApiError;
      setFormError(apiError.status === 400 ? "프로필 이미지를 다시 업로드한 뒤 시도해주세요." : GENERIC_ERROR_MESSAGE);
    }
  }

  const displayImageUrl = previewUrl ?? profile.profileImageUrl ?? undefined;
  const isSaving = updateProfileMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <Pencil aria-hidden />
          프로필 수정
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>프로필 수정</DialogTitle>
          <DialogDescription>프로필 이미지, 닉네임, 소개를 변경할 수 있어요.</DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-5"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void form.handleSubmit(onSubmit)(event);
          }}
        >
          {formError && (
            <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive-text">
              {formError}
            </p>
          )}

          <div className="flex items-center gap-4">
            <Avatar className="size-16">
              <AvatarImage src={displayImageUrl} alt="" />
              <AvatarFallback className="text-lg">{profile.nickname.slice(0, 1)}</AvatarFallback>
            </Avatar>
            <Label
              htmlFor="edit-profile-image"
              className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-md border border-input px-3 text-sm font-medium hover:bg-muted has-disabled:pointer-events-none has-disabled:opacity-50"
            >
              <Camera aria-hidden className="size-4" />
              {isUploadingImage ? "업로드 중..." : "이미지 변경"}
              <input
                id="edit-profile-image"
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="sr-only"
                disabled={isUploadingImage}
                onChange={(event) => void handleFileChange(event)}
              />
            </Label>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-profile-nickname">닉네임</Label>
            <Input
              id="edit-profile-nickname"
              aria-invalid={!!form.formState.errors.nickname}
              aria-describedby={form.formState.errors.nickname ? "edit-profile-nickname-error" : undefined}
              {...form.register("nickname")}
            />
            {form.formState.errors.nickname && (
              <p id="edit-profile-nickname-error" role="alert" className="text-xs text-destructive-text">
                {form.formState.errors.nickname.message}
              </p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-profile-bio">소개</Label>
            <Textarea
              id="edit-profile-bio"
              rows={3}
              placeholder="나를 소개해보세요"
              aria-invalid={!!form.formState.errors.bio}
              aria-describedby={form.formState.errors.bio ? "edit-profile-bio-error" : undefined}
              {...form.register("bio")}
            />
            {form.formState.errors.bio && (
              <p id="edit-profile-bio-error" role="alert" className="text-xs text-destructive-text">
                {form.formState.errors.bio.message}
              </p>
            )}
          </div>

          <DialogFooter>
            <Button type="submit" disabled={isSaving || isUploadingImage}>
              {isSaving ? "저장 중..." : "저장"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
