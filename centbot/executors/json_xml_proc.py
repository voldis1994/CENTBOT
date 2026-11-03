"""JSON and XML processing module."""

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
        src = workdir / "input.json"
        if not src.exists():
            src.write_text(json.dumps({"report": {"title": "Demo", "items": [{"id": 1, "value": "a"}]}}), encoding="utf-8")
        data = json.loads(src.read_text(encoding="utf-8"))
        root = Element("report")
        self._to_xml(root, data.get("report", data))
        xml_bytes = tostring(root, encoding="utf-8")
        out = workdir / "output.xml"
        out.write_bytes(xml_bytes)
        return ExecutionResult(ok=True, category=self.category, output={"bytes": len(xml_bytes)}, artifacts=[str(out)])

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
