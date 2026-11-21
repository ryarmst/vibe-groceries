import { mountChat } from "../../lib/chat.js";
import { h } from "../../lib/ui.js";

export async function render(el, [threadId]) {
  const box = h("div", { class: "card", style: { padding: 0, overflow: "hidden" } });
  el.append(box);
  mountChat(box, { threadId: threadId || null, onThread: (id) => history.replaceState(null, "", id ? `#/chat/${id}` : "#/chat") });
  box.querySelector(".chat").style.height = "calc(100vh - 110px)";
}
