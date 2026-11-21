"""Dev only: a scripted OpenAI-compatible endpoint (streaming) to exercise the chat UI without a real model.

- last message is a tool result → a short streamed summary
- user mentions "list" → asks to add Milk to the grocery list (a confirm-tier tool)
- otherwise → calls shopping_get_context, then summarizes
"""

import http.server
import json
import time


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"data": [{"id": "fake-model"}]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["content-length"])))
        msgs = req["messages"]
        last = msgs[-1]
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()

        def send(obj):
            self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode())
            self.wfile.flush()

        if last["role"] == "tool":
            text = f"Done. The tool said: {last['content'][:160]}"
            for i in range(0, len(text), 12):
                send({"choices": [{"delta": {"content": text[i:i + 12]}}]})
                time.sleep(0.03)
        else:
            user = last.get("content") or ""
            if "list" in user.lower():
                call = {"name": "grocery_list_add", "arguments": json.dumps({"items": [{"name": "Milk", "quantity": "4 L"}]})}
            else:
                call = {"name": "shopping_get_context", "arguments": "{}"}
            send({"choices": [{"delta": {"content": "Let me check. "}}]})
            send({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": f"c{time.time_ns()}", "function": call}]}}]})
        send({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 900, "completion_tokens": 40}})
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("127.0.0.1", 8766), H).serve_forever()
