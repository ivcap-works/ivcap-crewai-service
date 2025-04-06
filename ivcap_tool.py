from __future__ import annotations

from typing import Any, Callable, Dict, Optional
import json
import re
from pprint import pprint
import random

from pydantic.v1 import BaseModel
from langchain_core.tools.simple import Tool
from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools.base import BaseTool
from langchain_core.runnables import RunnableConfig

from datamodel_code_generator import DataModelType, PythonVersion
from datamodel_code_generator.model import get_data_model_types
from datamodel_code_generator.parser.jsonschema import JsonSchemaParser
import requests

def ivcap_tool(name: str, **kwargs: Any) -> Tool:
    url = "http://localhost:8000"
    resp = requests.get(url)
    if resp.status_code >= 300:
        raise Exception(f"can't connect to service '{name}' - {resp.status_code}")
    info = resp.json()
    service = IvcapService.from_service_info(info, url, name, kwargs)
    # pprint(service)
    return service

def ivcap_tool_test(name: str, **kwargs: Any) -> Callable[[], Tool]:
    import json

    with open(f"{name}.json", 'r') as f:
        data = json.load(f)
    url = "http://localhost:8000"
    service = IvcapService.from_service_info(data, url, name, kwargs)
    return lambda: service

class IvcapService(BaseTool):
    name: str
    description: str
    args_schema: type[BaseModel]
    service_props: Optional[BaseModel]

    url: str

    def _run(
        self,
        *args: Any,
        config: RunnableConfig,
        run_manager: Optional[CallbackManagerForToolRun] = None,
        **kwargs: Any,
    ) -> str:
        action = self.args_schema(**kwargs)
        payload = {
            "action": action.dict(),
            "service": self.service_props.dict()
        }
        headers = {
            "Content-Type": "application/json"
        }
        resp = requests.post(self.url, data=json.dumps(payload), headers=headers)
        if resp.status_code >= 300:
            raise Exception(f"Failed ({resp.status_code}) to call service '{self.name} - {resp.text}")
        jresp = resp.json()
        result = jresp.get("result", None)
        if not result:
            print(f">>>> Service '{self.name}' did not return a 'result'")
        return result

    @classmethod
    def from_service_info(cls, jinfo: Dict, url: str, serviceURN: str, kwargs: Any) -> IvcapService:
        name = jinfo.get("name", None)
        if not name:
            raise Exception(f"Missing 'name' in service info - '{serviceURN}'")
        model_prefix = to_camel_case(name)
        service_s = jinfo.pop("service_schema", None)
        if service_s:
            service_schema = schema_to_model(service_s, model_prefix+"Service")
            service_props = service_schema(**kwargs)
        else:
            service_props = None
        action_s = jinfo.pop("action_schema", None)
        if action_s:
            args_schema = schema_to_model(action_s, model_prefix+"Action")
        else:
            raise Exception(f"Missing 'action_schema' in service info - '{serviceURN}'")
        # pprint(args_schema.schema())
        # pprint(jinfo)
        return IvcapService(args_schema=args_schema, service_props=service_props, url=url, **jinfo)

def to_camel_case(s):
    pa = re.split(r'[_-]', s)
    ccs = ''.join(x.capitalize() for x in pa)
    return ccs

def schema_to_model(
    schema: Dict,
    model_prefix="Model",
    print_source=False,
) -> BaseModel:
    id = random.randint(100000, 999999)
    rootClass = f"{model_prefix}{id}"
    schema["title"] = rootClass

    def name_generator(name):
        if name == rootClass:
            return rootClass
        return f"{name}{id}"

    dmt = get_data_model_types(
        DataModelType.PydanticBaseModel,
        target_python_version=PythonVersion.PY_311
    )

    parser = JsonSchemaParser(
        json.dumps(schema),
        custom_class_name_generator=name_generator,
        base_class="pydantic.v1.BaseModel",
        data_model_type=dmt.data_model,
        data_model_root_type=dmt.root_model,
        data_model_field_type=dmt.field_model,
        data_type_manager_type=dmt.data_type_manager,
        dump_resolve_reference_action=dmt.dump_resolve_reference_action,
    )
    result = parser.parse()
    result = result.replace("from pydantic import", "from pydantic.v1 import")
    if print_source: print(result)
    exec(result, globals())
    return globals()[rootClass]
