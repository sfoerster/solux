from __future__ import annotations

import fnmatch

from solus.modules._helpers import interpolate_env
from solus.modules.spec import ConfigField, ContextKey, Dependency, ModuleSpec
from solus.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("input.s3_watcher requires boto3. Install with: pip install boto3") from exc

    bucket = str(step.config.get("bucket", ""))
    if not bucket:
        raise RuntimeError("input.s3_watcher: 'bucket' is required")

    prefix = str(step.config.get("prefix", ""))
    endpoint_url = step.config.get("endpoint_url")
    aws_access_key_id = interpolate_env(str(step.config.get("aws_access_key_id", "") or ""))
    aws_secret_access_key = interpolate_env(str(step.config.get("aws_secret_access_key", "") or ""))
    pattern = str(step.config.get("pattern", "*"))
    output_key = str(step.config.get("output_key", "s3_objects"))
    limit = int(step.config.get("limit", 100))

    session_kwargs: dict = {}
    if aws_access_key_id:
        session_kwargs["aws_access_key_id"] = aws_access_key_id
    if aws_secret_access_key:
        session_kwargs["aws_secret_access_key"] = aws_secret_access_key

    client_kwargs: dict = {"service_name": "s3"}
    if endpoint_url:
        client_kwargs["endpoint_url"] = str(endpoint_url)
    client_kwargs.update(session_kwargs)

    try:
        s3 = boto3.client(**client_kwargs)
        paginator = s3.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

        objects: list[dict] = []
        for page in pages:
            for obj in page.get("Contents", []):
                key = str(obj.get("Key", ""))
                name = key.split("/")[-1]
                if not fnmatch.fnmatch(name, pattern):
                    continue
                if endpoint_url:
                    url = f"{str(endpoint_url).rstrip('/')}/{bucket}/{key}"
                else:
                    url = f"s3://{bucket}/{key}"
                objects.append(
                    {
                        "key": key,
                        "url": url,
                        "size": obj.get("Size", 0),
                        "etag": str(obj.get("ETag", "")).strip('"'),
                    }
                )
                if limit > 0 and len(objects) >= limit:
                    break
            if limit > 0 and len(objects) >= limit:
                break
    except Exception as exc:
        raise RuntimeError(f"input.s3_watcher: S3 error: {exc}") from exc

    ctx.data[output_key] = objects
    ctx.data["display_name"] = f"s3://{bucket}/{prefix}"
    ctx.logger.info("s3_watcher: found %d objects in s3://%s/%s", len(objects), bucket, prefix)
    return ctx


MODULE = ModuleSpec(
    name="s3_watcher",
    version="0.1.0",
    category="input",
    description="List objects from an S3 (or MinIO) bucket.",
    handler=handle,
    aliases=("input.s3",),
    dependencies=(Dependency(name="boto3", kind="binary", hint="pip install boto3"),),
    config_schema=(
        ConfigField(name="bucket", description="S3 bucket name", required=True),
        ConfigField(name="prefix", description="Key prefix filter", default=""),
        ConfigField(name="endpoint_url", description="Custom endpoint URL (e.g. for MinIO)"),
        ConfigField(name="aws_access_key_id", description="AWS key ID (supports ${env:VAR})"),
        ConfigField(name="aws_secret_access_key", description="AWS secret (supports ${env:VAR})"),
        ConfigField(name="pattern", description="Glob pattern to match object names", default="*"),
        ConfigField(name="output_key", description="Context key for objects list", default="s3_objects"),
        ConfigField(name="limit", description="Max objects to return", type="int", default=100),
    ),
    reads=(),
    writes=(
        ContextKey("s3_objects", "List of object dicts (key, url, size, etag)"),
        ContextKey("display_name", "s3://bucket/prefix"),
    ),
    safety="trusted_only",
    network=True,
)
