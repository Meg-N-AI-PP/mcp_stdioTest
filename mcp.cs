using Azure;
using Azure.AI.OpenAI;
using Azure.Identity;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using ModelContextProtocol.Server;
using OpenAI;
using System.ComponentModel;

[Description("Get the code of project name BBAC")]
static string GetCode([Description("Get the code of a project, the project parameter is the name of the project")] string project)
{
    if (project == "BBAC")
    {
        return $"the code of project {project} is 88888888";
    }
    if (project == "DMCDV")
    {
        return $"the code of project {project} is 65UTTV";
    }
    else
    {
        return "no code";
    }
}

var getCodeFunction = AIFunctionFactory.Create(
    GetCode,
    name: "GetProjectCode",
    description: "Return the code of a project by its name"
);

AIAgent agent = new AzureOpenAIClient(
    new Uri("https://meg-2570-resource.openai.azure.com"),
    new AzureKeyCredential("3dmbukpwJQQJ99BFACHYHv6XJ3w3AAAAACOGGLmE"))
        .GetChatClient("gpt-4.1")
        .CreateAIAgent(instructions: "You're an agent to send user code of project, you will send the code to the user", name: "M Agents", tools:[getCodeFunction]);


//Console.WriteLine(await agent.RunAsync("Give me the code of project BBAC"));

McpServerTool tool = McpServerTool.Create(agent.AsAIFunction());
McpServerTool tool1 = McpServerTool.Create(getCodeFunction);

//Console.WriteLine(tool.ProtocolTool);

HostApplicationBuilder builder = Host.CreateEmptyApplicationBuilder(settings: null);
builder.Services
    .AddMcpServer()
    .WithStdioServerTransport()
    .WithTools([tool]);

await builder.Build().RunAsync();