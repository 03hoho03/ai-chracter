export type ChatMessagesCursor = {
  beforeCreatedAt: string;
  beforeId: string;
};

export const chatMessagesKeys = {
  all: ["chat-messages"] as const,
  list: (roomId: string, cursor: ChatMessagesCursor) =>
    [...chatMessagesKeys.all, "list", roomId, cursor.beforeCreatedAt, cursor.beforeId] as const,
};
