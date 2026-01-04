import streamlit as st
from fastmcp import Client
import asyncio
import json
import logging
import subprocess
import os
from pathlib import Path
from datetime import datetime
from adapters.ollama_adapter import OllamaAdapter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# MCP client
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://mcp_server:8000/sse")
SCOREBOARD_FILE = Path(__file__).parent / "results" / "scoreboard.json"

st.set_page_config(page_title="Agent Benchmarker", page_icon="🧪", layout="wide")

# Initialize session state
if "results" not in st.session_state:
    st.session_state.results = []
if "logs" not in st.session_state:
    st.session_state.logs = []
if "running" not in st.session_state:
    st.session_state.running = False
if "current_task" not in st.session_state:
    st.session_state.current_task = None
if "selected_model" not in st.session_state:
    st.session_state.selected_model = "qwen3"


def load_manifest():
    manifest_path = Path(__file__).parent / "tasks" / "manifest.json"
    with open(manifest_path) as f:
        return json.load(f)


def load_scoreboard():
    """Load scoreboard from file."""
    if SCOREBOARD_FILE.exists():
        with open(SCOREBOARD_FILE) as f:
            return json.load(f)
    return {"runs": []}


def save_scoreboard(scoreboard):
    """Save scoreboard to file."""
    SCOREBOARD_FILE.parent.mkdir(exist_ok=True)
    with open(SCOREBOARD_FILE, 'w') as f:
        json.dump(scoreboard, f, indent=2)


def save_run_to_scoreboard(model_name: str, results: list):
    """Save a benchmark run to the scoreboard."""
    scoreboard = load_scoreboard()

    total_tests = sum(r["tests"]["total"] for r in results)
    total_passed = sum(r["tests"]["passed"] for r in results)
    total_failed = sum(r["tests"]["failed"] for r in results)

    run_entry = {
        "id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "timestamp": datetime.now().isoformat(),
        "model": model_name,
        "summary": {
            "tasks_run": len(results),
            "total_tests": total_tests,
            "passed": total_passed,
            "failed": total_failed,
            "pass_rate": round((total_passed / total_tests * 100), 1) if total_tests > 0 else 0
        },
        "task_results": [
            {
                "task_name": r["task_name"],
                "agent_status": r.get("agent_status", "unknown"),
                "tests_passed": r["tests"]["passed"],
                "tests_failed": r["tests"]["failed"],
                "tests_total": r["tests"]["total"]
            }
            for r in results
        ]
    }

    scoreboard["runs"].append(run_entry)
    save_scoreboard(scoreboard)
    return run_entry


def add_log(message, level="info"):
    st.session_state.logs.append({"message": message, "level": level})


async def execute_tool_calls(calls, messages, mcp_instance: Client, status_container):
    for call in calls:
        status_container.write(f"🔧 Calling: `{call.function.name}`")
        add_log(f"Calling tool: {call.function.name}")
        logging.info(f"Calling tool: {call.function.name} with arguments: {call.function.arguments}")
        result = await mcp_instance.call_tool_mcp(call.function.name, call.function.arguments)
        logging.info(f"Result: {result}")
        messages.append({'role': 'tool', 'content': result.content[0].text})


async def run_agent_iteration(model, messages, tools, mcp_instance, status_container, think=False):
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
        await execute_tool_calls(response.message.tool_calls, messages, mcp_instance, status_container)

    return messages


async def run_agent_for_task(task_number: int, model_name: str, status_container):
    """Run the agent for a specific task."""
    logging.info(f"Starting agent for task {task_number} with model {model_name}")
    model = OllamaAdapter(model_name=model_name)
    fastmcp = Client(MCP_SERVER_URL)

    async with fastmcp:
        tools = await fastmcp.list_tools()
        agent_tools = [tool for tool in tools if tool.name in ['list_files', 'read_file', 'write_file', 'exec', 'get_container_logs']]

        task = await fastmcp.call_tool("get_task", {"task_number": task_number})
        messages = json.loads(task.content[0].text)

        status_container.write("📦 Setting up sandbox container...")
        add_log("Setting up sandbox container")
        log = await fastmcp.call_tool("setup_container")
        logging.info(f"Workspace initialized: {log.content[0].text}")

        iteration = 0
        max_iterations = 50
        done = False

        while not done and iteration < max_iterations:
            iteration += 1
            status_container.write(f"🔄 Agent iteration {iteration}...")
            add_log(f"Agent iteration {iteration}")

            messages = await run_agent_iteration(model, messages, agent_tools, fastmcp, status_container, think=False)
            last_message = messages[-1]

            if last_message['role'] == 'assistant' and not last_message.tool_calls:
                logging.info(f"Final response: {last_message.content}")
                status_container.write("🚀 Ensuring server is running...")
                add_log("Ensuring server is running")
                messages.append({'role': 'user', 'content': "run the server"})
                await run_agent_iteration(model, messages, agent_tools, fastmcp, status_container, think=False)
                done = True

        return done


def run_newman_tests(task_name: str) -> dict:
    """Run Newman tests for a task and return results."""
    test_file = Path(__file__).parent / "tasks" / "tests" / f"{task_name}.json"

    # Create artifacts directory for logs
    artifacts_dir = Path(__file__).parent / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if not test_file.exists():
        add_log(f"Test file not found: {test_file}", "error")
        return {
            "task_name": task_name,
            "status": "skipped",
            "message": f"No test file found: {task_name}.json",
            "tests": {"total": 0, "passed": 0, "failed": 0, "details": []}
        }

    result_file = artifacts_dir / f"newman-{task_name}-{timestamp}.json"
    cmd = [
        "newman", "run", str(test_file),
        "--reporters", "json,cli",
        "--reporter-json-export", str(result_file)
    ]

    add_log(f"Running: {' '.join(cmd)}", "info")

    try:
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        # Save stdout/stderr as artifacts
        stdout_file = artifacts_dir / f"newman-{task_name}-{timestamp}-stdout.txt"
        stderr_file = artifacts_dir / f"newman-{task_name}-{timestamp}-stderr.txt"
        with open(stdout_file, 'w') as f:
            f.write(process.stdout or "")
        with open(stderr_file, 'w') as f:
            f.write(process.stderr or "")

        add_log(f"Newman exit code: {process.returncode}", "info")
        add_log(f"Artifacts saved to: {artifacts_dir}", "info")

        if process.stderr:
            add_log(f"Newman stderr: {process.stderr[:500]}", "error")

        if result_file.exists():
            with open(result_file) as f:
                newman_result = json.load(f)

            run_stats = newman_result.get("run", {}).get("stats", {})
            assertions = run_stats.get("assertions", {})

            add_log(f"Newman stats: {json.dumps(run_stats)}", "info")

            total = assertions.get("total", 0)
            failed = assertions.get("failed", 0)
            passed = total - failed

            details = []
            executions = newman_result.get("run", {}).get("executions", [])
            for execution in executions:
                item_name = execution.get("item", {}).get("name", "Unknown")
                assertions_list = execution.get("assertions", [])
                for assertion in assertions_list:
                    details.append({
                        "name": f"{item_name}: {assertion.get('assertion', 'test')}",
                        "passed": assertion.get("error") is None,
                        "error": assertion.get("error", {}).get("message") if assertion.get("error") else None
                    })

            return {
                "task_name": task_name,
                "status": "completed",
                "artifact_path": str(result_file),
                "tests": {
                    "total": total,
                    "passed": passed,
                    "failed": failed,
                    "details": details
                }
            }
        else:
            add_log(f"Result file not found: {result_file}", "error")
            return {
                "task_name": task_name,
                "status": "error",
                "message": f"Newman did not produce results. Exit code: {process.returncode}. stderr: {process.stderr}",
                "tests": {"total": 0, "passed": 0, "failed": 0, "details": []}
            }

    except subprocess.TimeoutExpired:
        add_log("Newman timed out", "error")
        return {
            "task_name": task_name,
            "status": "timeout",
            "message": "Newman tests timed out after 120 seconds",
            "tests": {"total": 0, "passed": 0, "failed": 0, "details": []}
        }
    except Exception as e:
        add_log(f"Newman exception: {str(e)}", "error")
        logging.exception(f"Newman failed for {task_name}")
        return {
            "task_name": task_name,
            "status": "error",
            "message": str(e),
            "tests": {"total": 0, "passed": 0, "failed": 0, "details": []}
        }


async def run_benchmark(task_ids: list, model_name: str, progress_bar, status_container):
    """Run benchmark for selected tasks."""
    manifest = load_manifest()
    st.session_state.results = []
    st.session_state.logs = []

    for i, task_id in enumerate(task_ids):
        if task_id >= len(manifest["tasks"]):
            continue

        task = manifest["tasks"][task_id]
        task_name = task["name"]
        st.session_state.current_task = task_name

        progress_bar.progress((i) / len(task_ids), text=f"Running: {task['title']}")
        status_container.subheader(f"Task: {task_name}")
        add_log(f"Starting task: {task_name}", "info")

        # Run agent
        try:
            agent_success = await run_agent_for_task(task_id, model_name, status_container)
            agent_status = "completed" if agent_success else "failed"
            add_log(f"Agent completed: {agent_status}", "success" if agent_success else "error")
        except Exception as e:
            logging.exception(f"Agent failed for task {task_name}")
            agent_status = "error"
            add_log(f"Agent error: {str(e)}", "error")
            status_container.error(f"Agent error: {str(e)}")

        # Run tests
        status_container.write("🧪 Running Newman tests...")
        add_log(f"Running tests for {task_name}")
        test_result = run_newman_tests(task_name)
        test_result["agent_status"] = agent_status
        st.session_state.results.append(test_result)

        if test_result["tests"]["failed"] == 0 and test_result["tests"]["total"] > 0:
            add_log(f"Tests passed: {test_result['tests']['passed']}/{test_result['tests']['total']}", "success")
        else:
            add_log(f"Tests: {test_result['tests']['passed']}/{test_result['tests']['total']} passed", "error")

    progress_bar.progress(1.0, text="Complete!")

    # Save to scoreboard
    if st.session_state.results:
        save_run_to_scoreboard(model_name, st.session_state.results)
        add_log(f"Results saved to scoreboard", "success")

    st.session_state.running = False
    st.session_state.current_task = None


# UI - Tabs
tab_benchmark, tab_scoreboard = st.tabs(["🧪 Run Benchmark", "🏆 Scoreboard"])

with tab_benchmark:
    st.title("Agent Benchmarker")
    st.caption("Test AI agents on coding tasks")

    # Model selection
    col_model, col_spacer = st.columns([2, 3])
    with col_model:
        model_name = st.text_input("Model Name", value=st.session_state.selected_model,
                                   help="Enter the Ollama model name to use")
        st.session_state.selected_model = model_name

    # Load tasks
    manifest = load_manifest()
    tasks = manifest["tasks"]

    # Task selection
    st.subheader("Tasks")
    col1, col2 = st.columns([3, 1])

    with col1:
        selected_tasks = []
        for idx, task in enumerate(tasks):
            if st.checkbox(f"**{task['name']}** - {task['title']}", value=True, key=f"task_{idx}"):
                selected_tasks.append(idx)

    with col2:
        st.write("")
        st.write("")
        run_all = st.button("▶️ Run All Tasks", use_container_width=True, disabled=st.session_state.running)
        run_selected = st.button("▶️ Run Selected", use_container_width=True, disabled=st.session_state.running)

    # Progress section
    if run_all or run_selected:
        task_ids = list(range(len(tasks))) if run_all else selected_tasks

        if not task_ids:
            st.warning("Please select at least one task to run.")
        elif not model_name:
            st.warning("Please enter a model name.")
        else:
            st.session_state.running = True
            st.session_state.results = []
            st.session_state.logs = []

            st.subheader("Progress")
            progress_bar = st.progress(0, text="Starting...")
            status_container = st.container()

            asyncio.run(run_benchmark(task_ids, model_name, progress_bar, status_container))
            st.rerun()

    # Results section
    if st.session_state.results:
        st.subheader("Results")

        # Summary metrics
        total_tests = sum(r["tests"]["total"] for r in st.session_state.results)
        total_passed = sum(r["tests"]["passed"] for r in st.session_state.results)
        total_failed = sum(r["tests"]["failed"] for r in st.session_state.results)
        pass_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Tasks Run", len(st.session_state.results))
        col2.metric("Total Tests", total_tests)
        col3.metric("Passed", total_passed)
        col4.metric("Failed", total_failed)
        col5.metric("Pass Rate", f"{pass_rate:.0f}%")

        # Results table
        for result in st.session_state.results:
            with st.expander(f"**{result['task_name']}** - Agent: {result['agent_status']} | Tests: {result['tests']['passed']}/{result['tests']['total']}"):
                if result["status"] == "skipped":
                    st.info(result.get("message", "No tests available"))
                elif result["status"] == "error":
                    st.error(result.get("message", "Error running tests"))
                else:
                    for detail in result["tests"]["details"]:
                        if detail["passed"]:
                            st.success(f"✓ {detail['name']}")
                        else:
                            st.error(f"✗ {detail['name']}")
                            if detail.get("error"):
                                st.caption(f"  Error: {detail['error']}")

    # Logs section
    if st.session_state.logs:
        with st.expander("📋 Execution Logs", expanded=False):
            for log in st.session_state.logs:
                if log["level"] == "error":
                    st.error(log["message"])
                elif log["level"] == "success":
                    st.success(log["message"])
                else:
                    st.write(log["message"])

with tab_scoreboard:
    st.title("🏆 Scoreboard")
    st.caption("Historical benchmark results by model")

    scoreboard = load_scoreboard()
    runs = scoreboard.get("runs", [])

    if not runs:
        st.info("No benchmark runs recorded yet. Run some benchmarks to see results here!")
    else:
        # Get unique models
        models = list(set(run["model"] for run in runs))

        # Model filter
        col_filter, col_clear = st.columns([3, 1])
        with col_filter:
            filter_model = st.selectbox("Filter by Model", ["All Models"] + sorted(models))
        with col_clear:
            st.write("")
            if st.button("🗑️ Clear Scoreboard", type="secondary"):
                save_scoreboard({"runs": []})
                st.rerun()

        # Filter runs
        filtered_runs = runs if filter_model == "All Models" else [r for r in runs if r["model"] == filter_model]

        # Summary by model
        st.subheader("Model Comparison")

        model_stats = {}
        for run in runs:
            model = run["model"]
            if model not in model_stats:
                model_stats[model] = {
                    "runs": 0,
                    "total_tests": 0,
                    "passed": 0,
                    "failed": 0
                }
            model_stats[model]["runs"] += 1
            model_stats[model]["total_tests"] += run["summary"]["total_tests"]
            model_stats[model]["passed"] += run["summary"]["passed"]
            model_stats[model]["failed"] += run["summary"]["failed"]

        # Display model comparison table
        if model_stats:
            comparison_data = []
            for model, stats in sorted(model_stats.items()):
                pass_rate = (stats["passed"] / stats["total_tests"] * 100) if stats["total_tests"] > 0 else 0
                comparison_data.append({
                    "Model": model,
                    "Runs": stats["runs"],
                    "Total Tests": stats["total_tests"],
                    "Passed": stats["passed"],
                    "Failed": stats["failed"],
                    "Pass Rate": f"{pass_rate:.1f}%"
                })

            st.dataframe(comparison_data, use_container_width=True, hide_index=True)

        # Run history
        st.subheader("Run History")

        for run in reversed(filtered_runs[-20:]):  # Show last 20 runs
            timestamp = datetime.fromisoformat(run["timestamp"]).strftime("%Y-%m-%d %H:%M")
            summary = run["summary"]
            pass_rate = summary["pass_rate"]

            # Color based on pass rate
            if pass_rate >= 80:
                icon = "🟢"
            elif pass_rate >= 50:
                icon = "🟡"
            else:
                icon = "🔴"

            with st.expander(f"{icon} **{run['model']}** - {timestamp} | {summary['passed']}/{summary['total_tests']} tests ({pass_rate}%)"):
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Tasks", summary["tasks_run"])
                col2.metric("Passed", summary["passed"])
                col3.metric("Failed", summary["failed"])
                col4.metric("Pass Rate", f"{pass_rate}%")

                st.write("**Task Results:**")
                for task in run["task_results"]:
                    status_icon = "✅" if task["tests_failed"] == 0 and task["tests_total"] > 0 else "❌"
                    st.write(f"- {status_icon} **{task['task_name']}**: {task['tests_passed']}/{task['tests_total']} tests (Agent: {task['agent_status']})")
