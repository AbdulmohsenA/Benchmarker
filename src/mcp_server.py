import os
import docker
from fastmcp import FastMCP
from fastmcp.prompts.prompt import Message
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

WORKDIR = os.path.abspath("sandbox")
CONTAINER_NAME = "sandbox_container"

mcp = FastMCP("code-agent-tools")
docker_client = docker.from_env()

global sandbox_container

def run_in_container(cmd: str):
    container = docker_client.containers.get(CONTAINER_NAME)

    result = container.exec_run(
        cmd,
        workdir="/app",
        tty=True,
    )

    stdout = result.output.decode("utf-8") if result.output else ""
    return f"exit_code={result.exit_code}\n{stdout}"

@mcp.tool
def execute_tests(output_path) -> str: 
    os.makedirs(output_path, exist_ok=True)

    print("Running dynamic tests")
    container = docker_client.containers.run(
        image="postman/newman",
        command=[
            "run",
            "tests.json",
            "-r", "json",
            "--reporter-json-export", "report.json"
        ],
        volumes={
            output_path: {
                "bind": "/etc/newman",
                "mode": "rw"
            }
        },
        working_dir="/etc/newman",
        tty=True,
        detach=True,
        remove=True
    )

    return f"Test report saved to {os.path.join(output_path, 'report.json')}"

@mcp.tool
def setup_container():
    global sandbox_container
    try:
        sandbox_container = docker_client.containers.get(CONTAINER_NAME)
        if not sandbox_container.status == 'running':
            sandbox_container.start()
    except docker.errors.NotFound:
        sandbox_container = docker_client.containers.run(
            "node:22-slim",
            name=CONTAINER_NAME,
            volumes={WORKDIR: {'bind': '/app', 'mode': 'rw'}},
            working_dir="/app",
            detach=True,
            tty=True,
            ports={'5000/tcp': 5000},
        )
    
    # Clean up the workspace
    print(sandbox_container.exec_run("ls"))
    exit_code, output = sandbox_container.exec_run("sh -c 'rm -r /app/*'")
    return f"{output.decode()}, Exit code: {exit_code}"

@mcp.tool
def list_files() -> str:
    """Lists all files in the workspace."""
    files = []
    exclude_dirs = { "node_modules", ".git", "__pycache__", ".venv" }
    for root, dirs, filenames in os.walk(WORKDIR):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for f in filenames:
            files.append(os.path.relpath(os.path.join(root, f), WORKDIR))
    return "\n".join(files)

@mcp.tool
def read_file(path: str) -> str:
    """
    Reads the content of a file.
    
    Args:
        path (str): The relative path to the file.

    Returns:
        str: The content of the file or an error message if not found.
    """

    full = os.path.join(WORKDIR, path)
    if not os.path.isfile(full):
        return f"Error: {path} not found"
    return open(full, "r").read()

@mcp.tool
def write_file(path: str, content: str) -> str:
    """
    Writes content to a file.

    Args:
        path (str): The relative path to the file.
        content (str): The content to write to the file.

    Returns:
        str: A confirmation message.
    """


    full = os.path.join(WORKDIR, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content)
    return "ok"

@mcp.tool
def exec(command: str) -> str:
    """
    Executes a shell command in the Docker container.
    Args:
        command (str): The shell command to execute.
    Returns:
        str: The command output.
    """

    return run_in_container(command)

@mcp.prompt
def get_system_prompt() -> str:
    return """
You are a coding agent that edits and manages a project workspace.

Your primary goal is to understand the user’s intent, plan the required code changes, and then reliably apply them using the available tools. Always reason step-by-step internally, but only output tool calls or final answers — never expose your internal reasoning.

You may ONLY interact with the workspace through the tools listed below. Do not invent tools or assume file contents. When unsure, inspect the workspace first.

AVAILABLE TOOLS

1) list_files()
   - Lists all files in the workspace.

2) read_file(path: string)
   - Reads and returns the content of the given file path.

3) write_file(path: string, content: string)
   - Creates or overwrites a file with the given content.

5) exec(command: string)
   - Executes a shell command in workspace (e.g., to install packages, run the server, etc.)

GENERAL PRINCIPLES

- Be deterministic and precise.
- Prefer minimal, safe edits over large rewrites.
- ALWAYS read relevant files BEFORE modifying them.
- NEVER guess file contents.
- Maintain existing style and conventions when possible.
- Validate logic before writing files.

WHEN TO USE TOOLS

Use:
- list_files — to discover the workspace layout
- read_file — before changing or depending on a file
- write_file — to create or update files
- install_package — only when truly required
- exec — for running code or verifying changes
"""

@mcp.prompt
def get_user_prompt() -> str:
    return """
I need you to create a full Express.js server in JavaScript with the following specifications:

1. **Server Setup**
   - Use Express.js framework.
   - Run the server on host `0.0.0.0` and port `5000`.
   - Ensure all dependencies (`express`, `sqlite3`, `jsonwebtoken`, `bcrypt` or similar) are installed and included in `package.json`.

2. **Routes**
   - **GET /**  
     - Respond with status 200 and plain text: `"Hello, World!"`.
   
   - **GET /health**  
     - Respond with status 200 and JSON: `{ "status": "healthy" }`.

   - **POST /register**  
     - Accept JSON payload: `{ "username": "<string>", "password": "<string>" }`.
     - Hash the password using bcrypt (or similar secure hashing).
     - Store the user credentials in an SQLite3 database (`users` table).
     - Return JSON with a success message and optionally a JWT token.

   - **POST /login**  
     - Accept JSON payload: `{ "username": "<string>", "password": "<string>" }`.
     - Validate credentials against the SQLite3 database.
     - If valid, return a JWT token in JSON.
     - If invalid, return status 401 with a JSON error message.

     Ensure that the server runs using npm start

     Run the server after implementation using exec to ensure it starts correctly.
"""

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
