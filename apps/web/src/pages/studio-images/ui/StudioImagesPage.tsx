import { GenerateImagesForm } from "../../../features/generate-images";

export function StudioImagesPage() {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-6 py-10">
      <div className="flex flex-col gap-1.5">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">이미지 생성</h1>
        <p className="text-sm text-muted-foreground">
          프롬프트와 스타일, 비율을 입력해 AI로 이미지를 생성해요.
        </p>
      </div>

      <GenerateImagesForm />
    </main>
  );
}
