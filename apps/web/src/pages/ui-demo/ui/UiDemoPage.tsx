import { useState } from "react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ai-character-chat/ui/components/select";
import { toast } from "sonner";

export function UiDemoPage() {
  const [nickname, setNickname] = useState("");

  return (
    <main className="mx-auto flex max-w-lg flex-col gap-8 p-6">
      <header>
        <h1 className="text-lg font-semibold">packages/ui 데모</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Button · Dialog · Input · Select · Toast 프리미티브 확인용 화면입니다.
        </p>
      </header>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">Button</h2>
        <div className="flex flex-wrap gap-2">
          <Button>기본</Button>
          <Button variant="secondary">보조</Button>
          <Button variant="outline">아웃라인</Button>
          <Button variant="ghost">고스트</Button>
          <Button variant="destructive">삭제</Button>
          <Button variant="link">링크</Button>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">Input</h2>
        <Input
          name="nickname"
          placeholder="닉네임을 입력하세요"
          value={nickname}
          onChange={(event) => setNickname(event.target.value)}
        />
      </section>

      <section className="flex flex-col items-start gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">Select</h2>
        <Select defaultValue="story">
          <SelectTrigger>
            <SelectValue placeholder="콘텐츠 유형" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="story">스토리</SelectItem>
            <SelectItem value="character">캐릭터</SelectItem>
          </SelectContent>
        </Select>
      </section>

      <section className="flex flex-col items-start gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">Dialog</h2>
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="outline">다이얼로그 열기</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>발행 전 확인</DialogTitle>
              <DialogDescription>
                이 캐릭터를 지금 발행하시겠어요? 발행 후에도 언제든 수정할 수 있어요.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter showCloseButton>
              <Button>발행하기</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </section>

      <section className="flex flex-col items-start gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">Toast</h2>
        <Button
          variant="secondary"
          onClick={() => toast.success("저장되었습니다")}
        >
          토스트 띄우기
        </Button>
      </section>
    </main>
  );
}
