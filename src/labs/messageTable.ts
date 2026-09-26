/** One handler per message type of a lab's union. */
export type MessageHandlers<M extends { type: string }> = {
  readonly [K in M["type"]]: (message: Extract<M, { type: K }>) => Promise<void> | void;
};

export type MessageRoute = (message: { type: string }) => Promise<void> | void;

/**
 * The message table: each webview message type routed to the one controller that handles it. Two controllers
 * handling the same type is a programming error, reported when the Workbench opens.
 */
export function buildMessageTable(controllers: readonly { readonly handlers: object }[]): ReadonlyMap<string, MessageRoute> {
  const table = new Map<string, MessageRoute>();
  for (const controller of controllers) {
    for (const [type, handler] of Object.entries(controller.handlers as Record<string, MessageRoute>)) {
      if (table.has(type)) throw new Error(`Two Workbench controllers handle the "${type}" message.`);
      table.set(type, handler);
    }
  }
  return table;
}
