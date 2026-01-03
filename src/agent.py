from fastmcp import Client
import asyncio
import os
import logging
from adapters.ollama_adapter import OllamaAdapter
from utils import wait_for_server
import requests
from types import SimpleNamespace
import json
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

fastmcp = Client("http://mcp_server:8000/sse")

async def execute_tool_calls(calls, messages, mcp_instance: Client):
    for call in calls:
        logging.info(f"Calling tool: {call.function.name} with arguments: {call.function.arguments}")
        result = await mcp_instance.call_tool_mcp(call.function.name, call.function.arguments)
        logging.info(f"Result: {result}")
        messages.append({'role':'tool', 'content':result.content[0].text})

async def run_agent_iteration(model, messages, tools, mcp_instance, think=False):

    response = model.chat(
        messages=messages,
        tools=tools,
        think=think,
        options={
            "seed": 2222,
            "temperature": 0
        }
    )

    messages.append(response['message'])

    if response.message.tool_calls:
        await execute_tool_calls(response.message.tool_calls, messages, mcp_instance)

    return messages

async def run_agent(task_number):

    logging.info("Starting agent..")
    model = OllamaAdapter(model_name="qwen3")

    async with fastmcp:
        # Get the initialization data
        tools = await fastmcp.list_tools()

        agent_tools = [tool for tool in tools if tool.name in ['list_files', 'read_file', 'write_file', 'exec', 'get_container_logs']]
        # Task setup
        task = await fastmcp.call_tool("get_task", {"task_number": task_number})
        messages = json.loads(task.content[0].text)

        # Start the workspace
        log = await fastmcp.call_tool("setup_container")
        logging.info(f"Workspace initialized: {log.content[0].text}")

        # Main agent loop
        done = False
        while not done:
            messages = await run_agent_iteration(model, messages, agent_tools, mcp_instance=fastmcp, think=False)
            last_message = messages[-1]
            if last_message['role'] == 'assistant' and not last_message.tool_calls:
                logging.info(f"Final response: {last_message.content}")

                # Means the agent didn't run the server, running automatically:
                messages.append({'role': 'user', 'content':"run the server"})
                await run_agent_iteration(model, messages, agent_tools, mcp_instance=fastmcp, think=False)
                done = True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent.py <task_number>")
        sys.exit(1)

    task_number = int(sys.argv[1])
    asyncio.run(run_agent(task_number))
