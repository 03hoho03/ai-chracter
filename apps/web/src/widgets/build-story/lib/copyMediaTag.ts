import { toast } from "sonner";

/** 칸의 표기를 복사하고 결과를 토스트로 알린다. 표의 칸 복사 버튼과 칸 상세의 표기 복사가 같은 문구를 쓴다. */
export async function copyMediaTag(tag: string) {
  try {
    await navigator.clipboard.writeText(tag);
    toast.success("이미지 표기를 복사했어요. 시작상황·프롤로그·에필로그·등록 설명에 붙여 넣으면 그 자리에 이미지가 보여요.");
  } catch {
    toast.error(`복사하지 못했어요. 직접 입력해 주세요: ${tag}`);
  }
}
