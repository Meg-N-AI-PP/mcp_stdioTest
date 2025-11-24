// agent.mjs
import dotenv from "dotenv";
import OpenAI from "openai";
import readline from "node:readline";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import {
  ListToolsResultSchema,
  CallToolResultSchema,
} from "@modelcontextprotocol/sdk/types.js";

dotenv.config();

// Use env key if you want, for now hard-coded (but DON'T commit a real key)
const key = ""; // or process.env.OPENAI_API_KEY
const openai = new OpenAI({ apiKey: key });

async function connectToMcp() {
  const transport = new StdioClientTransport({
    command: "dotnet",
    args: [
      "run",
      "--project",
      "C:/Users/ADMIN/Source/Repos/customMCP.Test/customMCP.Test/customMCP.Test.csproj",
    ],
  });

  const client = new Client(
    { name: "node-mcp-agent", version: "1.0.0" },
    { capabilities: {} }
  );

  await client.connect(transport);
  return { client, transport };
}

async function getOpenAiTools(client) {
  const listResult = await client.request(
    { method: "tools/list" },
    ListToolsResultSchema
  );

  console.log(
    "MCP tools:",
    listResult.tools.map((t) => t.name)
  );

  return listResult.tools.map((tool) => ({
    type: "function",
    function: {
      name: tool.name,
      description: tool.description ?? "",
      parameters: tool.inputSchema ?? { type: "object", properties: {} },
    },
  }));
}

async function callMcpTool(client, toolCall) {
  const name = toolCall.function.name;
  const args = JSON.parse(toolCall.function.arguments || "{}");

  const result = await client.request(
    {
      method: "tools/call",
      params: { name, args },
    },
    CallToolResultSchema
  );

  const text =
    result.content?.[0]?.text ??
    JSON.stringify(result.content ?? [], null, 2);

  // ✅ Correct shape for tool result in chat.completions
  return {
    role: "tool",
    tool_call_id: toolCall.id,
    content: text,
  };
}

async function main() {
  const { client, transport } = await connectToMcp();
  const tools = await getOpenAiTools(client);

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  const messages = [];

  const ask = () => {
    rl.question("\nYou: ", async (input) => {
      if (!input.trim() || input.toLowerCase() === "quit") {
        await transport.close();
        rl.close();
        return;
      }

      messages.push({ role: "user", content: input });

      // First call: model can request tool calls
      const resp = await openai.chat.completions.create({
        model: "gpt-4o-mini",
        messages,
        tools,
      });

      let msg = resp.choices[0].message;
      if (msg.content) {
        console.log("\nAssistant (pre-tool):", msg.content);
      }

      // ✅ Only add tool_calls if they actually exist
      const assistantMessage = {
        role: "assistant",
        content: msg.content || "",
      };

      if (msg.tool_calls && msg.tool_calls.length > 0) {
        assistantMessage.tool_calls = msg.tool_calls;
      }

      messages.push(assistantMessage);

      if (msg.tool_calls && msg.tool_calls.length > 0) {
        // Call MCP tools
        for (const tc of msg.tool_calls) {
          const toolResultMessage = await callMcpTool(client, tc);
          messages.push(toolResultMessage);
        }

        // Final answer after tools
        const final = await openai.chat.completions.create({
          model: "gpt-4o-mini",
          messages,
        });

        const finalMsg = final.choices[0].message;
        console.log("\nAssistant:", finalMsg.content);
        if (finalMsg.content) {
          messages.push({
            role: "assistant",
            content: finalMsg.content,
          });
        }
      } else {
        // No tools used; the previous assistantMessage is already the final answer
      }

      ask();
    });
  };

  console.log("Connected to MCP server. Type questions (or 'quit').");
  ask();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
