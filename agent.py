import asyncio
import json
import os
import subprocess
from openai import OpenAI

# ========== CONFIG ==========
CSPROJ_PATH = r"C:\Users\ADMIN\Desktop\NetMCP\MCPTest\MCPTest\MCPTest.csproj"
OPENAI_MODEL = "gpt-4.1-mini"  # or "gpt-4.1", or whatever your project allows

key = "sk-proj-q7PaK7"
# Make sure OPENAI_API_KEY (project key) is set in env
client = OpenAI(api_key=key)


# ========== SIMPLE MCP STDIO CLIENT ==========
class McpClient:
    def __init__(self, command, args):
        self.command = command
        self.args = args
        self.proc = None
        self.message_id = 0
        self.pending = {}
        self.loop = asyncio.get_event_loop()

    async def start(self):
        self.proc = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        # Start background reader
        asyncio.create_task(self._reader())
        print("✅ Connected to MCP server")

    async def _reader(self):
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break

            try:
                msg = json.loads(line.decode("utf-8"))
            except Exception:
                print("⚠ Invalid JSON from MCP:", line)
                continue

            if "id" in msg and msg["id"] in self.pending:
                fut = self.pending.pop(msg["id"])
                fut.set_result(msg)

    async def request(self, method, params=None):
        self.message_id += 1
        msg_id = self.message_id

        message = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
        }
        if params is not None:
            message["params"] = params

        fut = self.loop.create_future()
        self.pending[msg_id] = fut

        self.proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        await self.proc.stdin.drain()

        return await fut

    async def list_tools(self):
        resp = await self.request("tools/list")
        return resp["result"]["tools"]

    async def call_tool(self, name, arguments):
        resp = await self.request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,  # 👈 IMPORTANT: must be "arguments"
            },
        )
        return resp["result"]


# ========== CONVERT MCP TO OPENAI TOOLS ==========
async def get_openai_tools(mcp: McpClient):
    tools_list = await mcp.list_tools()

    print("🔧 MCP tools available:", [t["name"] for t in tools_list])

    openai_tools = []
    for t in tools_list:
        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", "") or "",
                    "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
                },
            }
        )

    print("🔧 OpenAI tools passed to model:")
    print(json.dumps(openai_tools, indent=2))
    return openai_tools


# ========== TOOL CALL HELPER ==========
async def call_mcp_tool(mcp: McpClient, tool_call):
    func = tool_call.function
    name = func.name
    try:
        args = json.loads(func.arguments or "{}")
    except Exception:
        args = {}

    result = await mcp.call_tool(name, args)

    # MCP result.content is usually a list of { type, text, ... }
    content_blocks = result.get("content", [])
    if content_blocks and "text" in content_blocks[0]:
        text = content_blocks[0]["text"]
    else:
        text = json.dumps(content_blocks, indent=2)

    print(f"\n[RAW MCP RESULT from {name}]:\n{text}\n")

    return {
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": text,
    }


# ========== MAIN CHAT LOOP ==========
async def main():
    # 1) Start MCP server (C#) via stdio
    mcp = McpClient(
        command="dotnet",
        args=["run", "--project", CSPROJ_PATH],
    )
    await mcp.start()

    # 2) Get tools from MCP and convert to OpenAI tools
    tools = await get_openai_tools(mcp)

    # 3) Chat loop
    messages = [
        {
            "role": "system",
            "content": (
                "You are an assistant that can use MCP tools when needed. "
                "For project code questions (e.g. code of project BBAC), "
                "you should call the appropriate MCP tool instead of guessing."
            ),
        }
    ]

    print("\nType messages (or 'quit' to exit).")
    while True:
        user_input = input("\nYou: ").strip()
        if not user_input or user_input.lower() in ("quit", "exit"):
            break

        messages.append({"role": "user", "content": user_input})

        # 4) First model call - may request tool calls
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=tools,
        )

        msg = resp.choices[0].message

        if msg.content:
            print("\nAssistant (pre-tool):", msg.content)

        # Save the assistant msg with tool_calls (if any)
        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [tc.to_dict() for tc in (msg.tool_calls or [])],
            }
        )

        # 5) If the model wants to call tools, do it via MCP
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_result_message = await call_mcp_tool(mcp, tc)
                messages.append(tool_result_message)

            # 6) Second model call with tool results
            final = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
            )
            final_msg = final.choices[0].message
            print("\nAssistant:", final_msg.content)
            if final_msg.content:
                messages.append(
                    {
                        "role": "assistant",
                        "content": final_msg.content,
                    }
                )
        else:
            # No tools used
            print("\nAssistant:", msg.content or "")
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                }
            )


if __name__ == "__main__":
    asyncio.run(main())
