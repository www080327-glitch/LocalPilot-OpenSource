"""Disposable SDK transport process; it has no LocalPilot tools or model access."""
import asyncio
from contextlib import AsyncExitStack
from datetime import timedelta
import importlib.metadata
import json
import os
import signal
import sys

from . import PROTOCOL_VERSION, SDK_VERSION
from .security import MAX_FRAME, digest, redact, validate_schema


async def run():
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (min(soft, 128), hard))
    if importlib.metadata.version("mcp") != SDK_VERSION:
        raise RuntimeError("Install the exact plugins extra SDK version")
    import anyio
    import httpx
    from mcp import ClientSession, StdioServerParameters, types
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client

    class Session(ClientSession):
        async def send_request(self, request, result_type, **kwargs):
            request_id = self._request_id  # Deliberately bound to the pinned SDK.
            try:
                return await super().send_request(request, result_type, **kwargs)
            except BaseException:
                with anyio.CancelScope(shield=True):
                    with anyio.move_on_after(.25):
                        await self.send_notification(types.ClientNotification(types.CancelledNotification(
                            params=types.CancelledNotificationParams(requestId=request_id, reason="Host cancelled or timed out"))))
                raise

    class BoundedStream(httpx.AsyncByteStream):
        def __init__(self, wrapped):
            self.wrapped = wrapped

        async def __aiter__(self):
            size = 0
            async for chunk in self.wrapped:
                size += len(chunk)
                if size > MAX_FRAME:
                    raise ValueError("HTTP response exceeds 1 MiB")
                yield chunk

        async def aclose(self):
            await self.wrapped.aclose()

    async def bound_response(response):
        response.stream = BoundedStream(response.stream)

    def emit(value):
        value = redact(value, secrets)
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        if len(data) > MAX_FRAME:
            data = b'{"failure":"output_limit","dispatched":true}'
        sys.stdout.buffer.write(data + b"\n")
        sys.stdout.buffer.flush()

    line = await asyncio.to_thread(sys.stdin.buffer.readline, MAX_FRAME + 1)
    config = json.loads(line)
    credentials = config.pop("_credentials", {})
    secrets = list(credentials.values())
    active = None

    def cancel():
        if active is not None:
            active.cancel()
    asyncio.get_running_loop().add_signal_handler(signal.SIGUSR1, cancel)
    timeout = config["timeout"]
    async with AsyncExitStack() as stack:
        if config["transport"] == "stdio":
            # The SDK adds its default environment; clear the worker environment
            # first so provider/operator credentials never reach the child.
            env = {key: credentials[ref] for key, ref in config.get("credential_env", {}).items()}
            stderr = stack.enter_context(open(os.devnull, "w"))
            streams = await stack.enter_async_context(stdio_client(StdioServerParameters(
                command=config["command"], args=config.get("args", []), env=env,
                cwd=os.getcwd()), errlog=stderr))
        else:
            headers = {}
            if config.get("bearer_credential"):
                headers["Authorization"] = "Bearer " + credentials[config["bearer_credential"]]
            client = await stack.enter_async_context(httpx.AsyncClient(
                headers=headers, timeout=httpx.Timeout(timeout), follow_redirects=False,
                trust_env=False, event_hooks={"response": [bound_response]}))
            streams = await stack.enter_async_context(streamable_http_client(config["url"], http_client=client))
        session = await stack.enter_async_context(Session(streams[0], streams[1],
            read_timeout_seconds=timedelta(seconds=timeout),
            client_info=types.Implementation(name="localpilot-client", version="0.1.0")))
        initialized = await session.initialize()
        if initialized.protocolVersion != PROTOCOL_VERSION:
            raise ValueError("Server did not negotiate the pinned protocol")
        capabilities = initialized.capabilities.model_dump(mode="json", exclude_none=True)

        async def pages(method, field):
            items, cursor, seen = [], None, set()
            for _ in range(8):
                result = await method(cursor=cursor)
                items.extend(item.model_dump(mode="json", exclude_none=True) for item in getattr(result, field))
                if len(items) > 128:
                    raise ValueError("Discovery exceeds 128 items")
                cursor = result.nextCursor
                if not cursor:
                    return items
                if cursor in seen:
                    raise ValueError("Repeated discovery cursor")
                seen.add(cursor)
            raise ValueError("Discovery exceeds 8 pages")

        async def catalog():
            tools = await pages(session.list_tools, "tools") if "tools" in capabilities else []
            resources = await pages(session.list_resources, "resources") if "resources" in capabilities else []
            templates = []
            if "resources" in capabilities:
                from mcp.shared.exceptions import McpError
                try:
                    templates = await pages(session.list_resource_templates, "resourceTemplates")
                except McpError as error:
                    if error.error.code != types.METHOD_NOT_FOUND:
                        raise
            prompts = await pages(session.list_prompts, "prompts") if "prompts" in capabilities else []
            for collection, key in ((tools, "name"), (resources, "uri"), (templates, "uriTemplate"), (prompts, "name")):
                if len({item[key] for item in collection}) != len(collection):
                    raise ValueError("Duplicate external identifiers")
                collection.sort(key=lambda item: item[key])
            for tool in tools:
                validate_schema(tool["inputSchema"])
                if "outputSchema" in tool:
                    validate_schema(tool["outputSchema"])
            value = {"protocol": initialized.protocolVersion,
                     "server": initialized.serverInfo.model_dump(mode="json", exclude_none=True),
                     "capabilities": capabilities, "tools": tools, "resources": resources,
                     "resource_templates": templates, "prompts": prompts}
            if len(json.dumps(value).encode()) > 256 * 1024:
                raise ValueError("Catalog exceeds 256 KiB")
            return value

        emit({"catalog": await catalog()})

        async def operation(request):
            method = request["method"]
            if method == "ping":
                await session.send_ping()
                return {"result": {"healthy": True}}
            current = await catalog()
            if method == "catalog":
                return {"catalog": current}
            if digest(current) != request["expected_catalog"]:
                return {"failure": "catalog_changed", "dispatched": False}
            args = request.get("arguments", {})
            if method == "tool":
                result = await session.call_tool(request["name"], args)
            elif method == "resource":
                result = await session.read_resource(types.AnyUrl(args["uri"]))
            elif method == "prompt":
                result = await session.get_prompt(args["name"], args.get("arguments", {}))
            else:
                raise ValueError("Unsupported worker method")
            return {"result": result.model_dump(mode="json", by_alias=True, exclude_none=True)}

        while True:
            line = await asyncio.to_thread(sys.stdin.buffer.readline, MAX_FRAME + 1)
            if not line:
                return
            if len(line) > MAX_FRAME:
                raise ValueError("Host frame too large")
            request = json.loads(line)
            if request["method"] == "close":
                return
            active = asyncio.create_task(operation(request))
            try:
                with anyio.fail_after(timeout):
                    emit(await active)
            except asyncio.CancelledError:
                emit({"failure": "cancelled", "dispatched": True})
            except Exception as error:
                # Never relay exception messages, HTTP bodies or stderr.
                emit({"failure": type(error).__name__, "dispatched": True})
            finally:
                active = None


def main():
    try:
        asyncio.run(run())
    except BaseException as error:
        sys.stdout.write(json.dumps({"failure": type(error).__name__, "dispatched": False}) + "\n")
        sys.stdout.flush()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
