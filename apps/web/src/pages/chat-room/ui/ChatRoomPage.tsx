import { ChatRoomView } from "@/widgets/chat-room";

export function ChatRoomPage({ roomId }: { roomId: string }) {
  // 방이 바뀌면 화면을 새로 마운트한다. 같은 라우트에서 파라미터만 바뀌면 리마운트가 없어, 입력창의 글과 전송 상태(오류
  // 배너)가 앞 방의 것으로 남고 방마다 따로 두는 입력 초안이 엇갈린다.
  return <ChatRoomView key={roomId} roomId={roomId} />;
}
