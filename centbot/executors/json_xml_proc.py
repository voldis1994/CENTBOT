"""JSON and XML processing — requires real input.json (or input.xml)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from centbot.executors.base import ExecutionResult, Executor


class JsonXmlProcessor(Executor):
    category = "json_xml"

    def execute(self, task: dict[str, Any], workdir: Path) -> ExecutionResult:
        workdir.mkdir(parents=True, exist_ok=True)
        src_json = workdir / "input.json"
        src_xml = workdir / "input.xml"
        if src_json.exists():
            data = json.loads(src_json.read_text(encoding="utf-8"))
            root = Element("report")
            self._to_xml(root, data.get("report", data) if isinstance(data, dict) else data)
            xml_bytes = tostring(root, encoding="utf-8")
            out = workdir / "output.xml"
            out.write_bytes(xml_bytes)
            return ExecutionResult(ok=True, category=self.category, output={"bytes": len(xml_bytes)}, artifacts=[str(out)])
        if src_xml.exists():
            out = workdir / "output.json"
            # Minimal XML→JSON via ElementTree text dump
            from xml.etree.ElementTree import parse

            tree = parse(src_xml)
            payload = {tree.getroot().tag: tree.getroot().text}
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return ExecutionResult(ok=True, category=self.category, output={"root": tree.getroot().tag}, artifacts=[str(out)])
        from centbot.quality.task_intent import is_create_output_task, missing_input_error

        if is_create_output_task(task, extensions=(".json", ".xml")):
            # Task asks to produce JSON/XML — synthesize a structured deliverable from the brief
            payload = {
                "title": task.get("title"),
                "description": task.get("description"),
                "generated_by": "CENTBOT",
                "platform": task.get("platform"),
                "external_id": task.get("external_id"),
            }
            out = workdir / "output.json"
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return ExecutionResult(ok=True, category=self.category, output={"generated": True}, artifacts=[str(out)])
        return ExecutionResult(
            ok=False,
            category=self.category,
            error=missing_input_error(["input.json", "input.xml"]),
        )

    def _to_xml(self, parent: Element, data: Any) -> None:
        if isinstance(data, dict):
            for key, value in data.items():
                child = SubElement(parent, str(key))
                self._to_xml(child, value)
        elif isinstance(data, list):
            for item in data:
                child = SubElement(parent, "item")
                self._to_xml(child, item)
        else:
            parent.text = "" if data is None else str(data)
