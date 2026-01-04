import ollama
import os

# This should adapt generic information coming from FASTMCP to ollama specific format
class OllamaAdapter():

    def __init__(self, model_name='qwen3'):
        self.model_name = model_name
        # Explicitly create client with host from environment
        host = os.environ.get('OLLAMA_HOST', 'http://localhost:11434')
        self.client = ollama.Client(host=host)

    def format_messages(self, messages):
        
        # TODO: Adapt message formatting if needed
        return messages

    def format_tools(self, tools):
        # This is needed since Ollama expects a certain format different from what the MCP provides
        def tool_to_definition(tool):
            return {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema
                    }
                }
        
        return [tool_to_definition(tool) for tool in tools]

    def chat(self, messages, tools=None, **kwargs):
        response = self.client.chat(
            model=self.model_name,
            messages=self.format_messages(messages),
            tools=self.format_tools(tools),
            **kwargs
        )
        return response
