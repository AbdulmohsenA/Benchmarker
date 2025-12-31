from fastmcp import Client
import asyncio
import os
import logging
from adapters.ollama_adapter import OllamaAdapter
from utils import wait_for_server
import requests
from types import SimpleNamespace

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

fastmcp = Client("http://mcp_server:8000/mcp")

async def take_action(calls, messages, mcp_instance: Client):
    for call in calls:
        logging.info(f"Calling tool: {call.function.name} with arguments: {call.function.arguments}")
        async with mcp_instance:
            result = await mcp_instance.call_tool_mcp(call.function.name, call.function.arguments)
        logging.info(f"Result: {result}")
        messages.append({'role':'tool', 'content':result.content[0].text})

async def agent_loop(model, messages, tools, mcp_instance, think=False):

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
        await take_action(response.message.tool_calls, messages, mcp_instance)
        
    return messages

async def start_agent():

    logging.info("Starting agent..")
    async with fastmcp:
        # Get the initialization data
        tools = await fastmcp.list_tools()
        SYSTEM_PROMPT = await fastmcp.get_prompt("get_system_prompt")
        USER_PROMPT = await fastmcp.get_prompt("get_user_prompt")

        # Start the workspace
        log = await fastmcp.call_tool("setup_container")
        logging.info(f"Workspace initialized: {log.content[0].text}")

    # Set up model
    model = OllamaAdapter(model_name="qwen3")

    messages=[
    {'role':'system', 'content':SYSTEM_PROMPT.messages[0].content.text},
    {'role': 'user', 'content':USER_PROMPT.messages[0].content.text},
    ]

    # Main agent loop
    done = False
    while not done:
        messages = await agent_loop(model, messages, tools, mcp_instance=fastmcp, think=False)
        last_message = messages[-1]
        if last_message['role'] == 'assistant' and not last_message.tool_calls:
            logging.info(f"Final response: {last_message.content}")
            
            # Means the agent didn't run the server, running automatically:
            func = SimpleNamespace(
                    function=SimpleNamespace(
                        name="exec",
                        arguments={"command": "npm start"}
                    )
                )
            
            logging.info(func)
            await take_action([
                func
            ], messages, fastmcp)

            done = True
 

if __name__ == "__main__":

    asyncio.run(start_agent())