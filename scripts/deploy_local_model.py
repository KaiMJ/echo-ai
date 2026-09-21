"""Manage local vLLM using Echo’s packaged model templates."""

import argparse
import json
import os
import shlex
import subprocess
from pathlib import Path

import yaml
from dotenv import load_dotenv

from echo_ai.config import Config
from echo_ai.config.file import builtin_profile_names, read_model_profile

ROOT = Path(__file__).resolve().parents[1]
SERVER_FIELDS = {
    "revision",
    "cache_env",
    "tensor_parallel_size",
    "pipeline_parallel_size",
    "gpu_memory_utilization",
    "max_num_seqs",
    "tool_call_parser",
    "reasoning_parser",
}


def deployment(model, environment, profile=None):
    runtime, server = read_model_profile(profile or f"builtin:{model}")
    settings = Config(**runtime)
    if server.keys() != SERVER_FIELDS:
        raise ValueError(f"deployment requires exactly these keys: {sorted(SERVER_FIELDS)}")
    if settings.provider != "hosted_vllm":
        raise ValueError("Local deployment requires provider: hosted_vllm")
    for key in ("tensor_parallel_size", "pipeline_parallel_size", "max_num_seqs"):
        if type(server[key]) is not int or server[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    if not 0 < server["gpu_memory_utilization"] < 1:
        raise ValueError("gpu_memory_utilization must be between 0 and 1")
    revision = server["revision"]
    if (
        not isinstance(revision, str)
        or len(revision) != 40
        or any(c not in "0123456789abcdef" for c in revision)
    ):
        raise ValueError("revision must be an exact 40-character checkpoint commit")
    cache = environment.get(server["cache_env"]) or environment.get("ECHO_HF_HUB_CACHE")
    if not cache:
        raise ValueError(f"Set ECHO_HF_HUB_CACHE or {server['cache_env']} in .env")
    cache = Path(cache).expanduser().resolve()
    relative = Path("models--" + settings.model.replace("/", "--")) / "snapshots" / revision
    command = [str(Path("/hf") / relative), "--served-model-name", model, settings.model]
    for key in (
        "pipeline_parallel_size",
        "tensor_parallel_size",
        "gpu_memory_utilization",
        "max_num_seqs",
        "tool_call_parser",
        "reasoning_parser",
    ):
        command.extend(["--" + key.replace("_", "-"), str(server[key])])
    # The profile's context capacity is authoritative for both client and server.
    command.extend(
        [
            "--max-model-len",
            str(settings.context_tokens),
            "--enable-auto-tool-choice",
            "--language-model-only",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ]
    )
    override = {
        "services": {
            "inference": {
                "command": command,
                "volumes": [
                    {
                        "type": "bind",
                        "source": str(cache),
                        "target": "/hf",
                        "read_only": True,
                        "bind": {"create_host_path": False},
                    }
                ],
            }
        }
    }
    return settings, cache, cache / relative, yaml.safe_dump(override, sort_keys=False)


def validate(settings, cache, snapshot):
    if not snapshot.is_dir():
        raise ValueError(
            f"Model snapshot not found: {snapshot}\n"
            "Set ECHO_HF_HUB_CACHE to the hub directory containing models--* folders "
            "and download the exact revision specified by the profile. "
            "Run 'models' to see packaged revisions."
        )
    for filename in (
        "config.json",
        "tokenizer_config.json",
        "chat_template.jinja",
        "model.safetensors.index.json",
    ):
        file = snapshot / filename
        if not file.is_file():
            raise ValueError(f"Missing model file: {file}")
        if not file.resolve().is_relative_to(cache):
            raise ValueError(f"Model file escapes the mounted hub cache: {file}")
    index = json.loads((snapshot / "model.safetensors.index.json").read_text())
    for name in set(index["weight_map"].values()):
        file = snapshot / name
        if not file.is_file():
            raise ValueError(f"Missing weight shard: {file}")
        if not file.resolve().is_relative_to(cache):
            raise ValueError(f"Weight symlink escapes the mounted hub cache: {file}")
    print(
        f"Validated {settings.model}: context={settings.context_tokens}, max output={settings.max_tokens}",
        flush=True,
    )


def positive_int(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def list_models():
    for name in builtin_profile_names():
        runtime, server = read_model_profile(f"builtin:{name}")
        gpus = server["tensor_parallel_size"] * server["pipeline_parallel_size"]
        print(f"{name}: {runtime['model']}")
        print(f"  GPUs: {gpus}; context: {runtime['context_tokens']:,} tokens")
        print(f"  Revision: {server['revision']}")
        print(f"  Cache: {server['cache_env']} (fallback: ECHO_HF_HUB_CACHE)")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s models                 Show packaged models and GPU requirements
  %(prog)s qwen check             Validate downloaded weights and Compose config
  %(prog)s qwen up                Start the shared server and wait for readiness
  %(prog)s status                 Show the shared server's status
  %(prog)s logs --no-follow       Print recent logs and exit
  %(prog)s stop                   Stop the shared server

Qwen and Gemma share one server; starting either replaces the current model.
Weights must already be downloaded. See docs/guides/local-models.md.
""",
    )
    actions = ["models", "check", "up", "stop", "logs", "status", "config"]
    parser.add_argument("target", nargs="?", help="Model name, or models/status/logs/stop")
    parser.add_argument("action", nargs="?", choices=actions, help="Action for the selected model")
    parser.add_argument("--profile", type=Path, help="Custom profile for check/up/config")
    parser.add_argument(
        "--env-file", type=Path, help="Environment file (default: ECHO_ENV_FILE or checkout .env)"
    )
    parser.add_argument("--no-follow", action="store_true", help="Print logs and exit")
    parser.add_argument(
        "--tail", type=positive_int, default=100, help="Log lines to show (default: 100)"
    )
    parser.add_argument(
        "--wait-timeout",
        type=positive_int,
        default=1200,
        help="Seconds to wait for startup (default: 1200)",
    )
    args = parser.parse_args(argv)
    if args.target is None:
        parser.print_help()
        return
    if args.action:
        model, action = args.target, args.action
        if model not in builtin_profile_names():
            parser.error(
                f"unknown model {model!r}; choose from {', '.join(builtin_profile_names())}"
            )
    else:
        model, action = None, args.target
        if action not in actions:
            parser.error("specify an action, for example: qwen up; use 'models' to list models")
    if action in {"check", "up", "config"} and model is None:
        parser.error(f"{action} requires a model, for example: qwen {action}")
    if args.profile and action not in {"check", "up", "config"}:
        parser.error("--profile only applies to check/up/config")
    if action == "models":
        list_models()
        return

    explicit_env = args.env_file or os.getenv("ECHO_ENV_FILE")
    env_file = Path(explicit_env or ROOT / ".env").expanduser().resolve()
    if explicit_env and not env_file.is_file():
        raise ValueError(f"Environment file not found: {env_file}")
    load_dotenv(env_file, override=False)
    command = ["docker", "compose"]
    if env_file.is_file():
        command.extend(["--env-file", str(env_file)])
    command.extend(["-f", str(ROOT / "compose.yaml")])
    override = None
    if action in {"check", "up", "config"}:
        profile = args.profile.expanduser().resolve() if args.profile else None
        settings, cache, snapshot, override = deployment(model, os.environ, profile)
        command.extend(["-f", "-"])
        if action in {"check", "up"}:
            print(f"Model: {settings.model}\nSnapshot: {snapshot}", flush=True)
            validate(settings, cache, snapshot)
    commands = {
        "check": ["config", "--quiet"],
        "config": ["config"],
        "up": ["up", "-d", "--wait", "--wait-timeout", str(args.wait_timeout), "inference"],
        "stop": ["stop", "inference"],
        "logs": [
            "logs",
            "--tail",
            str(args.tail),
            *([] if args.no_follow else ["-f"]),
            "inference",
        ],
        "status": ["ps", "--all", "inference"],
    }
    if action == "up":
        print(f"Starting inference; waiting up to {args.wait_timeout}s for readiness…", flush=True)
    # Only deployment actions need a generated override; controls use the shared service.
    try:
        subprocess.run(
            [*command, *commands[action]],
            cwd=ROOT,
            input=override,
            text=True,
            check=True,
        )
    except FileNotFoundError as error:
        raise ValueError(
            "Docker was not found. Install Docker with the Compose plugin and NVIDIA GPU support."
        ) from error
    except subprocess.CalledProcessError as error:
        hint = (
            "Startup failed or timed out. The container may still be running. "
            "Run 'status' and 'logs --no-follow' to diagnose, or 'stop' to stop it."
            if action == "up"
            else f"Docker Compose {action} failed. Check the output above and that Docker is running."
        )
        raise ValueError(hint) from error
    if action == "check":
        print("Check passed: model files and Compose configuration are valid.")
    elif action == "up":
        profile_name = str(profile) if profile else f"builtin:{model}"
        endpoint = f"http://127.0.0.1:{os.getenv('ECHO_INFERENCE_PORT', '8001')}/v1"
        print(f"Server ready: {endpoint}")
        env_prefix = f"ECHO_ENV_FILE={shlex.quote(str(env_file))} " if env_file.is_file() else ""
        print(
            f"For Echo: {env_prefix}ECHO_MODEL_PROFILE={shlex.quote(profile_name)} "
            f"ECHO_BASE_URL={shlex.quote(endpoint)} uv run echo-ai"
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error
