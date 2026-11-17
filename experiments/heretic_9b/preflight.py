"""Read-only Heretic model compatibility preflight. No model load, downloads, or CUDA allocation."""
import argparse
import json
import sys
from pathlib import Path


def inspect_model(path: Path) -> dict:
    path = path.expanduser()
    if path.is_file():
        return {"compatible_layout": False, "reason": (
            "A single .safetensors/.gguf is not a complete Transformers model folder. "
            "The existing ComfyUI W4A8 encoder cannot be passed directly to Heretic."
        ), "path": str(path)}
    if not path.is_dir():
        return {"compatible_layout": False, "reason": "Not an existing model directory.", "path": str(path)}
    config = path / "config.json"
    if not config.is_file():
        return {"compatible_layout": False, "reason": "Missing config.json.", "path": str(path)}
    try:
        obj = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"compatible_layout": False, "reason": f"Cannot parse config.json: {exc}", "path": str(path)}
    if not isinstance(obj, dict) or not isinstance(obj.get("model_type"), str):
        return {"compatible_layout": False, "reason": "config.json missing model_type.", "path": str(path)}
    has_weights = any(path.glob("*.safetensors")) or (path/"model.safetensors.index.json").is_file()
    has_tokenizer = any((path/p).is_file() for p in ("tokenizer.json", "tokenizer.model", "tokenizer_config.json"))
    return {
        "compatible_layout": bool(has_weights and has_tokenizer),
        "reason": "Potential HF Transformers layout; actual model/Heretic support NOT verified." if has_weights and has_tokenizer
                  else "HF layout incomplete: missing weight shards or tokenizer assets.",
        "model_type": obj["model_type"],
        "weights_present": bool(has_weights),
        "tokenizer_present": bool(has_tokenizer),
        "path": str(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path, help="Local original HF model directory; does not download or load model.")
    args = parser.parse_args()
    result = inspect_model(args.model)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["compatible_layout"] else 2


if __name__ == "__main__":
    sys.exit(main())
