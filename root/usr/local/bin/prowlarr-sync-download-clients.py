#!/usr/bin/env python3

import base64
import copy
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


SUPPORTED_APPS = {
    "sonarr": {
        "api_base": "/api/v3",
        "display": "Sonarr",
        "supports_downloadclient_sync": True,
    },
    "radarr": {
        "api_base": "/api/v3",
        "display": "Radarr",
        "supports_downloadclient_sync": True,
    },
    "lidarr": {
        "api_base": "/api/v1",
        "display": "Lidarr",
        "supports_downloadclient_sync": True,
    },
    "readarr": {
        "api_base": "/api/v1",
        "display": "Readarr",
        "supports_downloadclient_sync": True,
    },
    "whisparr": {
        "api_base": "/api/v3",
        "display": "Whisparr",
        "supports_downloadclient_sync": True,
    },
    "lazylibrarian": {
        "api_base": None,
        "display": "LazyLibrarian",
        "supports_downloadclient_sync": False,
        "unsupported_reason": (
            "downstream API does not expose Servarr-style /downloadclient and /tag endpoints"
        ),
    },
    "mylar": {
        "api_base": None,
        "display": "Mylar",
        "supports_downloadclient_sync": False,
        "unsupported_reason": (
            "downstream API does not expose Servarr-style /downloadclient and /tag endpoints"
        ),
    },
}
DEFAULTS = {
    "PROWLARR_SYNC_ENABLED": "true",
    "PROWLARR_SYNC_URL": "http://127.0.0.1:9696",
    "PROWLARR_SYNC_INTERVAL": "300",
    "PROWLARR_SYNC_TIMEOUT": "15",
    "PROWLARR_SYNC_MANAGED_TAG": "prowlarr-sync-download-clients",
    "PROWLARR_SYNC_LOG_LEVEL": "info",
}
FIELD_KEYS = ("BaseUrl", "ApiKey", "AuthUsername", "AuthPassword", "ProwlarrUrl")
COPY_TOP_LEVEL_KEYS = {
    "name",
    "implementation",
    "configContract",
    "enable",
    "protocol",
    "priority",
}
IGNORE_TOP_LEVEL_KEYS = {
    "categories",
    "supportsCategories",
    "id",
    "fields",
    "message",
    "presets",
    "infoLink",
    "implementationName",
    "testCommand",
}


def env_bool(name):
    return os.getenv(name, DEFAULTS.get(name, "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def env_int(name):
    value = os.getenv(name, DEFAULTS[name]).strip()
    return max(1, int(value))


def configure_logging():
    level_name = os.getenv(
        "PROWLARR_SYNC_LOG_LEVEL", DEFAULTS["PROWLARR_SYNC_LOG_LEVEL"]
    ).strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [prowlarr-sync-download-clients] %(message)s",
    )


def load_prowlarr_api_key():
    env_key = os.getenv("PROWLARR_SYNC_API_KEY", "").strip()
    if env_key:
        return env_key

    config_path = "/config/config.xml"
    tree = ET.parse(config_path)
    root = tree.getroot()
    api_key = root.findtext("./ApiKey")
    if not api_key:
        raise RuntimeError("ApiKey not found in /config/config.xml")
    return api_key.strip()


def trim_slash(url):
    return url.rstrip("/")


def make_headers(api_key, auth_username=None, auth_password=None):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Api-Key": api_key,
    }
    if auth_username:
        token = base64.b64encode(
            f"{auth_username}:{auth_password or ''}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    return headers


def request_json(method, base_url, path, headers, payload=None, timeout=15):
    url = trim_slash(base_url) + path
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        if not body:
            return None
        return json.loads(body.decode("utf-8"))


def wait_for_prowlarr(base_url, headers, timeout):
    for path in ("/ping", "/api/v1/system/status"):
        try:
            request_json("GET", base_url, path, headers, timeout=timeout)
            return
        except Exception:
            continue

    logging.info("waiting for Prowlarr at %s", base_url)
    while True:
        try:
            request_json("GET", base_url, "/ping", headers, timeout=timeout)
            logging.info("Prowlarr is reachable")
            return
        except Exception as exc:
            logging.debug("Prowlarr readiness check failed: %s", exc)
            time.sleep(5)


def normalize_field_value(value):
    if isinstance(value, list):
        if all(isinstance(item, dict) and "value" in item for item in value):
            return sorted(value, key=lambda item: json.dumps(item["value"], sort_keys=True))
        if all(not isinstance(item, dict) for item in value):
            return sorted(value)
    return value


def field_map(resource):
    return {field.get("name"): field for field in resource.get("fields") or [] if field.get("name")}


def extract_application_settings(app):
    fields = field_map(app)
    return {name: (fields.get(name) or {}).get("value") for name in FIELD_KEYS}


def detect_app_kind(app):
    haystack = " ".join(
        str(app.get(key, "") or "")
        for key in ("implementation", "configContract", "name")
    ).lower()
    for kind in SUPPORTED_APPS:
        if kind in haystack:
            return kind
    return None


def managed_identity(resource):
    return (resource.get("implementation"), resource.get("name"))


def clone_json(value):
    return copy.deepcopy(value)


def build_field_list(schema_fields, existing_fields, prowlarr_fields):
    schema_fields = schema_fields or []
    existing_fields = existing_fields or []
    prowlarr_fields = prowlarr_fields or []
    schema_map = field_map({"fields": schema_fields})
    existing_map = field_map({"fields": existing_fields})
    prowlarr_map = field_map({"fields": prowlarr_fields})

    ordered_names = []
    for field in schema_fields + existing_fields:
        name = field.get("name")
        if name and name not in ordered_names:
            ordered_names.append(name)

    fields = []
    for name in ordered_names:
        if name in schema_map:
            item = clone_json(schema_map[name])
        elif name in existing_map:
            item = clone_json(existing_map[name])
        else:
            continue

        if name in prowlarr_map:
            item["value"] = normalize_field_value(prowlarr_map[name].get("value"))
        elif name in existing_map:
            item["value"] = normalize_field_value(existing_map[name].get("value"))
        else:
            item["value"] = normalize_field_value(item.get("value"))
        fields.append(item)

    return fields


def build_client_payload(prowlarr_client, schema_client, existing_client, managed_tag_id):
    schema_client = schema_client or {}
    existing_client = existing_client or {}
    payload = {}

    for key in COPY_TOP_LEVEL_KEYS:
        if key in prowlarr_client:
            payload[key] = clone_json(prowlarr_client.get(key))

    extra_keys = set(schema_client) | set(existing_client)
    for key in sorted(extra_keys):
        if key in payload or key in IGNORE_TOP_LEVEL_KEYS:
            continue
        if key in existing_client:
            payload[key] = clone_json(existing_client.get(key))
        elif key in schema_client:
            payload[key] = clone_json(schema_client.get(key))

    payload["fields"] = build_field_list(
        schema_client.get("fields"),
        existing_client.get("fields"),
        prowlarr_client.get("fields"),
    )

    tags = []
    for tag in existing_client.get("tags") or schema_client.get("tags") or []:
        if tag not in tags:
            tags.append(tag)
    if managed_tag_id not in tags:
        tags.append(managed_tag_id)
    payload["tags"] = sorted(tags)
    return payload


def canonicalize_resource(resource):
    def walk(value):
        if isinstance(value, dict):
            return {key: walk(value[key]) for key in sorted(value)}
        if isinstance(value, list):
            if value and all(isinstance(item, dict) and "name" in item for item in value):
                value = sorted(value, key=lambda item: item.get("name") or "")
            return [walk(item) for item in value]
        return value

    return walk(resource)


def ensure_tag(app_ctx, timeout):
    tags = request_json(
        "GET", app_ctx["base_url"], app_ctx["api_base"] + "/tag", app_ctx["headers"], timeout=timeout
    )
    label = app_ctx["managed_tag"]
    for tag in tags or []:
        if tag.get("label") == label:
            return tag["id"]

    created = request_json(
        "POST",
        app_ctx["base_url"],
        app_ctx["api_base"] + "/tag",
        app_ctx["headers"],
        {"label": label},
        timeout=timeout,
    )
    return created["id"]


def build_app_context(app, timeout, managed_tag):
    settings = extract_application_settings(app)
    kind = detect_app_kind(app)
    if not kind:
        logging.warning("unsupported application type: %s", app.get("name") or app.get("implementation"))
        return None

    app_meta = SUPPORTED_APPS[kind]
    if not app_meta["supports_downloadclient_sync"]:
        logging.warning(
            "skipping %s app %r: %s",
            app_meta["display"],
            app.get("name"),
            app_meta["unsupported_reason"],
        )
        return None

    base_url = (settings.get("BaseUrl") or "").strip()
    api_key = (settings.get("ApiKey") or "").strip()
    if not base_url or not api_key:
        logging.warning(
            "skipping %s app %r due to missing BaseUrl or ApiKey",
            app_meta["display"],
            app.get("name"),
        )
        return None

    return {
        "kind": kind,
        "display": app_meta["display"],
        "api_base": app_meta["api_base"],
        "base_url": trim_slash(base_url),
        "headers": make_headers(
            api_key,
            auth_username=(settings.get("AuthUsername") or "").strip(),
            auth_password=(settings.get("AuthPassword") or "").strip(),
        ),
        "sync_level": app.get("syncLevel"),
        "app_name": app.get("name") or app_meta["display"],
        "managed_tag": managed_tag,
        "timeout": timeout,
    }


def reconcile_app(app_ctx, prowlarr_clients, summary):
    timeout = app_ctx["timeout"]
    tag_id = ensure_tag(app_ctx, timeout)

    downstream_clients = request_json(
        "GET",
        app_ctx["base_url"],
        app_ctx["api_base"] + "/downloadclient",
        app_ctx["headers"],
        timeout=timeout,
    ) or []
    downstream_schema = request_json(
        "GET",
        app_ctx["base_url"],
        app_ctx["api_base"] + "/downloadclient/schema",
        app_ctx["headers"],
        timeout=timeout,
    ) or []

    schema_by_implementation = {
        item.get("implementation"): item
        for item in downstream_schema
        if item.get("implementation")
    }

    managed_existing = {}
    tagged_resources = []
    for client in downstream_clients:
        tags = client.get("tags") or []
        if tag_id in tags:
            tagged_resources.append(client)
            managed_existing[managed_identity(client)] = client

    desired = {}
    retained_identities = set()
    for prowlarr_client in prowlarr_clients:
        implementation = prowlarr_client.get("implementation")
        identity = managed_identity(prowlarr_client)
        schema_client = schema_by_implementation.get(implementation)
        if not schema_client:
            logging.warning(
                "%s %r: skipping unsupported download client implementation %r",
                app_ctx["display"],
                app_ctx["app_name"],
                implementation,
            )
            retained_identities.add(identity)
            summary["skipped_unsupported"] += 1
            continue

        retained_identities.add(identity)
        desired[identity] = build_client_payload(
            prowlarr_client,
            schema_client,
            managed_existing.get(identity),
            tag_id,
        )

    sync_level = app_ctx["sync_level"]
    for identity, payload in desired.items():
        existing = managed_existing.get(identity)
        if existing is None:
            request_json(
                "POST",
                app_ctx["base_url"],
                app_ctx["api_base"] + "/downloadclient",
                app_ctx["headers"],
                payload,
                timeout=timeout,
            )
            summary["created"] += 1
            continue

        if sync_level != "fullSync":
            continue

        candidate = clone_json(payload)
        candidate["id"] = existing["id"]

        current = build_client_payload(
            existing,
            schema_by_implementation.get(existing.get("implementation"), {}),
            existing,
            tag_id,
        )
        current["id"] = existing["id"]

        if canonicalize_resource(candidate) != canonicalize_resource(current):
            request_json(
                "PUT",
                app_ctx["base_url"],
                f"{app_ctx['api_base']}/downloadclient/{existing['id']}",
                app_ctx["headers"],
                candidate,
                timeout=timeout,
            )
            summary["updated"] += 1

    if sync_level == "fullSync":
        desired_identities = set(desired)
        for existing in tagged_resources:
            if managed_identity(existing) in desired_identities | retained_identities:
                continue
            request_json(
                "DELETE",
                app_ctx["base_url"],
                f"{app_ctx['api_base']}/downloadclient/{existing['id']}",
                app_ctx["headers"],
                timeout=timeout,
            )
            summary["deleted"] += 1


def sync_once():
    timeout = env_int("PROWLARR_SYNC_TIMEOUT")
    managed_tag = os.getenv(
        "PROWLARR_SYNC_MANAGED_TAG", DEFAULTS["PROWLARR_SYNC_MANAGED_TAG"]
    ).strip()
    prowlarr_url = trim_slash(os.getenv("PROWLARR_SYNC_URL", DEFAULTS["PROWLARR_SYNC_URL"]).strip())
    prowlarr_api_key = load_prowlarr_api_key()
    prowlarr_headers = make_headers(prowlarr_api_key)
    wait_for_prowlarr(prowlarr_url, prowlarr_headers, timeout)

    applications = request_json(
        "GET", prowlarr_url, "/api/v1/applications", prowlarr_headers, timeout=timeout
    ) or []
    prowlarr_clients = request_json(
        "GET", prowlarr_url, "/api/v1/downloadclient", prowlarr_headers, timeout=timeout
    ) or []

    summary = {
        "apps_processed": 0,
        "created": 0,
        "updated": 0,
        "deleted": 0,
        "skipped_unsupported": 0,
        "failed": 0,
    }

    for app in applications:
        if app.get("syncLevel") == "disabled":
            continue

        app_ctx = build_app_context(app, timeout, managed_tag)
        if app_ctx is None:
            summary["skipped_unsupported"] += 1
            continue

        summary["apps_processed"] += 1
        try:
            reconcile_app(app_ctx, prowlarr_clients, summary)
        except Exception as exc:
            summary["failed"] += 1
            logging.exception(
                "failed to reconcile %s app %r: %s",
                app_ctx["display"],
                app_ctx["app_name"],
                exc,
            )

    logging.info(
        "sync summary: apps_processed=%d created=%d updated=%d deleted=%d skipped_unsupported=%d failed=%d",
        summary["apps_processed"],
        summary["created"],
        summary["updated"],
        summary["deleted"],
        summary["skipped_unsupported"],
        summary["failed"],
    )


def main():
    configure_logging()
    if not env_bool("PROWLARR_SYNC_ENABLED"):
        logging.info("sync disabled via PROWLARR_SYNC_ENABLED")
        return 0

    try:
        sync_once()
        return 0
    except Exception as exc:
        logging.exception("fatal sync failure: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
