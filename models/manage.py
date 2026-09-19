"""Manage local vLLM using the same models/<name>.yaml profile as Echo."""

import argparse
import json
import os
import subprocess
from pathlib import Path

import yaml
from dotenv import load_dotenv

from echo_ai.config import Config
from echo_ai.config.file import read_model_profile

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


def deployment(model, environment):
    runtime, server = read_model_profile(ROOT / "models" / f"{model}.yaml")
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=[p.stem for p in (ROOT / "models").glob("*.yaml")])
    parser.add_argument("action", choices=["check", "up", "stop", "logs", "status", "config"])
    args = parser.parse_args()
    env_file = Path(os.getenv("ECHO_ENV_FILE", ROOT / ".env")).expanduser()
    load_dotenv(env_file, override=False)
    settings, cache, snapshot, override = deployment(args.model, os.environ)
    if args.action in {"check", "up"}:
        validate(settings, cache, snapshot)
    commands = {
        "check": ["config", "--quiet"],
        "config": ["config"],
        "up": ["up", "-d", "--wait", "--wait-timeout", "1200", "inference"],
        "stop": ["stop", "inference"],
        "logs": ["logs", "--tail", "100", "-f", "inference"],
        "status": ["ps", "inference"],
    }
    # Compose reads the generated override from stdin; no duplicate YAML to maintain.
    subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(ROOT / "compose.yaml"),
            "-f",
            "-",
            *commands[args.action],
        ],
        cwd=ROOT,
        input=override,
        text=True,
        check=True,
    )
    if args.action == "up":
        print(f"For Echo: ECHO_MODEL_PROFILE=models/{args.model}.yaml uv run echo-ai")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error
