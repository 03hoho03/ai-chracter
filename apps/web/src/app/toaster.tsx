import { Toaster } from "@ai-character-chat/ui/components/sonner";
import { useAtomValue } from "jotai";

import { themeAtom } from "../shared/model/theme";

/** 현재 테마를 Toaster에 연결하는 web 전용 래퍼 (admin은 래퍼 없이 기본 light). */
export function AppToaster() {
  return <Toaster theme={useAtomValue(themeAtom)} />;
}
