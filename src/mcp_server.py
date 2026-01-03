import os
import docker
from fastmcp import FastMCP
from fastmcp.prompts.prompt import Message
import logging
import json
import select
import time

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

WORKDIR = os.path.abspath("sandbox")
CONTAINER_NAME = "sandbox_container"

mcp = FastMCP("code-agent-tools")
docker_client = docker.from_env()

global sandbox_container


with open("./tasks/manifest.json", "r", encoding="utf-8") as file:

    tasks = json.load(file)['tasks']

def run_in_container(cmd: str, timeout: int = 15):

    container = docker_client.containers.get(CONTAINER_NAME)
    logging.info(f"Command: {cmd}")

    exec_id = docker_client.api.exec_create(
        container.id,
        f"sh -c '{cmd} 2>&1 | tee /proc/1/fd/1'",
        workdir="/app"
    )['Id']

    # Proper logging approach
    sock = docker_client.api.exec_start(exec_id, socket=True)
    sock._sock.settimeout(0.1)  # Set socket timeout for non-blocking behavior

    output_chunks = []
    start_time = time.time()
    buffer = b''

    try:
        while True:
            elapsed = time.time() - start_time

            if elapsed >= timeout:
                output = b''.join(output_chunks).decode('utf-8', errors='replace')
                output += "\n\n[The Process continues running in background...]"
                logging.info(output)
                return output

            try:
                chunk = sock._sock.recv(4096)
                if not chunk:
                    # No more data, process has finished
                    break

                buffer += chunk

                # Parse Docker stream multiplexing format
                # Each frame: [stream_type(1)][padding(3)][size(4)][payload(size)]
                while len(buffer) >= 8:
                    header = buffer[:8]
                    stream_type = header[0]
                    payload_size = int.from_bytes(header[4:8], byteorder='big')

                    if len(buffer) < 8 + payload_size:
                        # Not enough data yet, wait for more
                        break

                    payload = buffer[8:8 + payload_size]
                    output_chunks.append(payload)
                    buffer = buffer[8 + payload_size:]

            except Exception:
                # Socket timeout, continue to check elapsed time
                continue
    finally:
        sock.close()

    output = b''.join(output_chunks).decode('utf-8', errors='replace')
    logging.info(output)
    return output

def copy_to_container(src_path: str, dest_path: str = "/app"):
    """Copy files from host to container."""
    container = docker_client.containers.get(CONTAINER_NAME)

    import tarfile
    import io

    # Create a tar archive in memory
    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode='w') as tar:
        tar.add(src_path, arcname=os.path.basename(src_path))
    tar_stream.seek(0)

    # Put the archive in the container
    container.put_archive(dest_path, tar_stream)
    return True

def get_system_prompt() -> str:
    with open(f"./tasks/prompts/system-prompt.md", "r", encoding="utf-8") as file:
        return file.read()

@mcp.tool()
def get_task(task_number: int) -> list:

    task = tasks[task_number]
    prompt_path = f"{os.path.abspath(f"tasks/prompts/{task['id']}.md")}"
    with open(prompt_path, "r", encoding="utf-8") as file:
        prompt = file.read()

    return [
    {'role':'system', 'content':get_system_prompt()},
    {'role': 'user', 'content':prompt},
    ]

@mcp.tool
def setup_container():
    global sandbox_container

    try:
        existing_container = docker_client.containers.get(CONTAINER_NAME)
        logging.info(f"Removing existing container: {CONTAINER_NAME}")
        # force=True sends SIGKILL and removes the container in one go
        existing_container.remove(force=True)
    except docker.errors.NotFound:
        logging.info("No existing container to remove.")

    sandbox_container = docker_client.containers.run(
        "nikolaik/python-nodejs:python3.11-nodejs22-slim",
        name=CONTAINER_NAME,
        working_dir="/app",
        command="tail -f /dev/null", # To keep running when tty = False
        ports={'5000/tcp': 5000},
        detach=True,
        stdout=True,
        network=f"benchmarker_default",
        labels={
            "com.docker.compose.project": "benchmarker",
            "com.docker.compose.service": "sandbox",
        }
    )
    logging.info(f"Started fresh container: {CONTAINER_NAME}")

    # Clean up the workspace in container
    print(sandbox_container)
    print(sandbox_container.exec_run("ls"))
    # Clean up the workspace on host
    import shutil
    for item in os.listdir(WORKDIR):
        item_path = os.path.join(WORKDIR, item)
        if os.path.isfile(item_path):
            os.unlink(item_path)
        elif os.path.isdir(item_path) and item != 'node_modules':
            shutil.rmtree(item_path)

    return f"Fresh container created"

@mcp.tool
def terminate_container():
    global sandbox_container

    try:
        existing_container = docker_client.containers.get(CONTAINER_NAME)
        logging.info(f"Removing existing container: {CONTAINER_NAME}")
        # force=True sends SIGKILL and removes the container in one go
        existing_container.remove(force=True)
    except docker.errors.NotFound:
        logging.info("No existing container to remove.")

    return f"Sandbox terminated successfuly"

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

    # Copy the file to the container
    try:
        copy_to_container(full)
    except Exception as e:
        logger.error(f"Failed to copy file to container: {e}")

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

@mcp.tool()
def get_container_logs(tail_lines: int = 50):
    """
    Retrieve the most recent logs from the application container.
    Use this to debug if a command failed or to check status.
    Args:
        tail_lines (int): The amount of most recent log lines to retrieve
    Returns:
        Logs for the container
    """
    container = docker_client.containers.get(CONTAINER_NAME)

    logs = container.logs(tail=tail_lines, stderr=True, stdout=True)
    return logs.decode("utf-8")


if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=8000)
