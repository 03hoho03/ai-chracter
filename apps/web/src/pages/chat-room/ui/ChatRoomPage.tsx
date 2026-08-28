import { ChatRoomView } from "@/widgets/chat-room";

export function ChatRoomPage({ roomId }: { roomId: string }) {
  return <ChatRoomView roomId={roomId} />;
}
