import { toast } from "sonner";

/**
 * 코드 블록 복사. 권한 거부·비보안 컨텍스트(clipboard 자체가 없음)에서도 던지지 않고 실패를 알린다 —
 * 버튼 클릭 핸들러에서 부르므로 여기서 새는 예외는 받아 줄 곳이 없다.
 */
export async function copyCodeToClipboard(code: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(code);
    toast.success("코드를 복사했어요.");
  } catch {
    toast.error("코드를 복사하지 못했어요. 직접 선택해 복사해 주세요.");
  }
}
