#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import yaml
from jsonschema import Draft202012Validator


SPEC = "https://github.com/zach-blumenfeld/aip/tree/v0.3a3"
SCHEMA_ID = "https://raw.githubusercontent.com/zach-blumenfeld/aip/v0.3a3/assets/aip-schemas/procedure.schema.json"
SCHEMA_SHA256 = "3dfd95403f05ed5481dee5ce001e351a2264ac5cec6c411d1685e979cb196c5e"
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
TYPE = re.compile(r"(?:string|integer|float|boolean|object|list\[(?:string|integer|float|boolean|object)\])\Z")


class ValidationError(ValueError):
    pass


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValidationError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def validate_graph(body, root):
    steps = {step["name"]: step for step in body["steps"]}
    require(len(steps) == len(body["steps"]), "step names must be unique")
    ancestors = {}

    def visit(name, active):
        require(name in steps, f"unknown dependency: {name}")
        require(name not in active, f"dependency cycle at {name}")
        if name not in ancestors:
            parents = steps[name].get("depends_on", [])
            require(len(parents) == len(set(parents)), f"{name}: repeated dependency")
            reached = set(parents)
            for parent in parents:
                reached.update(visit(parent, active | {name}))
            ancestors[name] = reached
        return ancestors[name]

    producers = {}
    for name, step in steps.items():
        require(NAME.fullmatch(name) is not None, f"invalid step name: {name}")
        visit(name, set())
        script = step.get("script")
        if script:
            path = Path(script)
            require(not path.is_absolute() and path.parts[0] == "scripts" and ".." not in path.parts,
                    f"{name}: script must be under scripts/")
            target = (root / path).resolve()
            require(target.is_relative_to(root.resolve()) and target.is_file(), f"{name}: missing or external script: {script}")
        for direction in ("inputs", "outputs"):
            values = step.get(direction, [])
            require(len({item["name"] for item in values}) == len(values), f"{name}: duplicate {direction}")
            for item in values:
                require(TYPE.fullmatch(item.get("type", "")) is not None, f"{name}: missing or unsupported type for {item['name']}")
        for item in step.get("outputs", []):
            require(item["name"] not in producers, f"duplicate output: {item['name']}")
            producers[item["name"]] = (name, item)
        for reference in re.findall(r"\breferences/[\w./-]+\.md", step["description"]):
            target = (root / reference).resolve()
            require(target.is_relative_to(root.resolve()) and target.is_file(), f"missing reference: {reference}")

    for name, step in steps.items():
        for item in step.get("inputs", []):
            producer = producers.get(item["name"])
            if producer is None:
                require(item.get("description", "").startswith("External:"), f"{name}: unknown input: {item['name']}")
                continue
            source, output = producer
            require(source in ancestors[name], f"{name}: {item['name']} must depend on its producer {source}")
            require(item["type"] == output["type"], f"{name}: type mismatch for {item['name']}")
            require(not output.get("nullable", False) or item.get("nullable", False), f"{name}: nullable output requires nullable input: {item['name']}")
    return ancestors


def validate_skill(root):
    root = Path(root)
    text = (root / "SKILL.md").read_text()
    match = re.fullmatch(r"---\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    require(match is not None, "missing YAML frontmatter")
    metadata = yaml.load(match[1], Loader=UniqueLoader)
    require(isinstance(metadata, dict), "frontmatter must be an object")
    name = metadata.get("name", "")
    require(isinstance(name, str) and 1 <= len(name) <= 64 and NAME.fullmatch(name), "invalid skill name")
    require(name == root.resolve().name, "skill name must match directory")
    description = metadata.get("description")
    require(isinstance(description, str) and description.strip() and len(description) <= 1024, "invalid skill description")
    aip = metadata.get("metadata", {}).get("aip", {})
    require(aip.get("spec") == SPEC, "AIP spec must be pinned to v0.3a3")
    require(aip.get("schemaId") == SCHEMA_ID, "AIP schemaId does not match the upstream procedure schema")
    source = root / "source"
    require((source / "original-SKILL.md").is_file() and (source / "README.md").is_file(), "missing source provenance")
    schema_bytes = (source / "procedure.schema.json").read_bytes()
    require(hashlib.sha256(schema_bytes).hexdigest() == SCHEMA_SHA256, "bundled schema differs from pinned upstream schema")
    schema = json.loads(schema_bytes)
    require(schema["$id"] == aip["schemaId"] and schema["aip"]["spec"] == aip["spec"], "schema metadata mismatch")
    Draft202012Validator.check_schema(schema)
    fence = re.fullmatch(r"```(?:yaml|yml)\n(.*?)\n```\s*", match[2].strip(), re.DOTALL)
    require(fence is not None and "```" not in fence[1], "body must be exactly one fenced YAML block")
    body = yaml.load(fence[1], Loader=UniqueLoader)
    errors = list(Draft202012Validator(schema).iter_errors(body))
    require(not errors, "; ".join(error.message for error in errors))
    validate_graph(body, root)
    return body


def main():
    parser = argparse.ArgumentParser(description="Validate bundled AIP v0.3a3 skills and typed dependency graphs offline")
    parser.add_argument("skills", nargs="*", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "plugins/feature-graph/skills"
    paths = args.skills or [root / "feature-graph", root / "verify-changed"]
    failures = 0
    for path in paths:
        try:
            body = validate_skill(path)
            print(f"VALID: {path.name} ({len(body['steps'])} typed steps)")
        except (OSError, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError) as err:
            print(f"INVALID: {path}: {err}", file=sys.stderr)
            failures += 1
    return int(failures > 0)


if __name__ == "__main__":
    sys.exit(main())
