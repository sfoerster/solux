from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import quote, urlencode

from .sources import FileEntry, SourceEntry


def _human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{num_bytes} B"


def _fmt_time(ts: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _route_with_query(**params: str) -> str:
    return "/?" + urlencode(params)


def _build_footer() -> str:
    from datetime import datetime

    year = datetime.now().year
    return (
        "<footer style='margin:16px 16px 14px;color:#8fa8c1;font-size:12px;"
        "text-align:center;letter-spacing:.02em'>"
        f"Copyright &copy; {year} Steven Foerster"
        "</footer>"
    )


def _render_inline_markdown(text: str) -> str:
    chunks = text.split("`")
    rendered: list[str] = []
    for idx, chunk in enumerate(chunks):
        if idx % 2 == 1:
            rendered.append(f"<code>{html.escape(chunk)}</code>")
            continue
        escaped = html.escape(chunk)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"(?<!\*)\*(.+?)\*(?!\*)", r"<em>\1</em>", escaped)
        rendered.append(escaped)
    return "".join(rendered)


def markdown_to_html(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    out: list[str] = []
    in_list = False
    in_code = False
    code_lines: list[str] = []

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                out.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
                in_code = False
                code_lines = []
            else:
                if in_list:
                    out.append("</ul>")
                    in_list = False
                in_code = True
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            if in_list:
                out.append("</ul>")
                in_list = False
            level = len(heading_match.group(1))
            content = _render_inline_markdown(heading_match.group(2).strip())
            out.append(f"<h{level}>{content}</h{level}>")
            continue

        list_match = re.match(r"^\s*[-*]\s+(.+)$", line)
        if list_match:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_render_inline_markdown(list_match.group(1).strip())}</li>")
            continue

        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<p>{_render_inline_markdown(stripped)}</p>")

    if in_code:
        out.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
    if in_list:
        out.append("</ul>")
    if not out:
        return "<p class='muted'>No content.</p>"
    return "\n".join(out)


def render_file_content(file_entry: FileEntry | None) -> str:
    if file_entry is None:
        return "<p class='muted'>No output file selected.</p>"
    try:
        raw = file_entry.path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"<p>Failed to read file: {html.escape(str(exc))}</p>"

    if file_entry.name.endswith(".json"):
        try:
            parsed = json.loads(raw)
            raw = json.dumps(parsed, indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
        return f"<pre>{html.escape(raw)}</pre>"
    if file_entry.name.endswith(".md"):
        return f"<article class='markdown'>{markdown_to_html(raw)}</article>"
    return f"<pre>{html.escape(raw)}</pre>"


def build_page(
    entries: list[SourceEntry],
    selected_source: SourceEntry | None,
    selected_file: FileEntry | None,
    file_content: str,
    queue_status: dict[str, int],
    recent_jobs: list[dict[str, Any]],
    w_status: dict[str, object] | None = None,
    workflow_filter: str | None = None,
    configured_workflows: list[str] | None = None,
    configured_triggers: list[Any] | None = None,
    workflow_load_errors: int = 0,
    trigger_load_errors: int = 0,
    default_workflow: str = "audio_summary",
) -> str:
    from .sources import _source_label

    source_items_html: list[str] = []
    for entry in entries:
        href = _route_with_query(sid=entry.source_id)
        active_cls = (
            "source-card active" if selected_source and entry.source_id == selected_source.source_id else "source-card"
        )
        source_label = _source_label(entry.source_input)
        source_items_html.append(
            f"""
            <a class="{active_cls}" href="{href}">
              <div class="source-title">{html.escape(entry.title)}</div>
              <div class="source-meta">{html.escape(entry.source_id)} · {len(entry.files)} files</div>
              {"<div class='source-meta'>" + html.escape(source_label) + "</div>" if source_label else ""}
              <div class="source-meta">Updated {_fmt_time(entry.updated_at)}</div>
            </a>
            """
        )

    file_tabs_html = ""
    source_info_html = "<p class='muted'>No processed sources found yet.</p>"
    action_forms_html = ""
    if selected_source:
        sid_escaped = html.escape(selected_source.source_id)
        source_info_html = f"""
        <h2>{html.escape(selected_source.title)}</h2>
        <p class="muted"><strong>source_id:</strong> {html.escape(selected_source.source_id)}</p>
        <p class="muted"><strong>input:</strong> {html.escape(selected_source.source_input or selected_source.title)}</p>
        """
        tabs: list[str] = []
        for file_entry in selected_source.files:
            href = _route_with_query(sid=selected_source.source_id, file=file_entry.name)
            active_cls = "tab active" if selected_file and selected_file.name == file_entry.name else "tab"
            tabs.append(
                f"""
                <a class="{active_cls}" href="{href}">
                  {html.escape(file_entry.name)}
                  <span>{_human_size(file_entry.size_bytes)}</span>
                </a>
                """
            )
        file_tabs_html = "\n".join(tabs)

        action_forms_html = f"""
        <div class="action-forms">
          <form method="post" action="/delete"
                onsubmit="return confirm('Delete this source and all its files?')">
            <input type="hidden" name="sid" value="{sid_escaped}">
            <button class="danger-btn" type="submit">Delete source</button>
          </form>
          <form method="post" action="/rerun" class="rerun-form">
            <input type="hidden" name="sid" value="{sid_escaped}">
            <select name="mode">
              <option value="transcript">transcript</option>
              <option value="tldr">tldr</option>
              <option value="outline">outline</option>
              <option value="notes">notes</option>
              <option value="full" selected>full</option>
            </select>
            <select name="format">
              <option value="markdown" selected>markdown</option>
              <option value="text">text</option>
              <option value="json">json</option>
            </select>
            <button class="rerun-btn" type="submit">Re-run</button>
          </form>
        </div>
        """

    raw_link = "#"
    if selected_source and selected_file:
        raw_link = "/raw?" + urlencode(
            {
                "sid": selected_source.source_id,
                "file": selected_file.name,
            }
        )

    selected_default_workflow = default_workflow.strip() or "audio_summary"

    recent_job_html: list[str] = []
    for job in recent_jobs[:10]:
        status = html.escape(str(job.get("status", "unknown")))
        source = html.escape(str(job.get("source", "")))
        job_id = html.escape(str(job.get("job_id", "")))
        workflow_name = html.escape(str(job.get("workflow_name", selected_default_workflow)))
        recent_job_html.append(
            f"<div class='queue-row'><strong>{job_id}</strong> "
            f"<span class='chip'>{status}</span>"
            f"<div class='source-meta'>workflow: {workflow_name}</div>"
            f"<div class='source-meta'>{source}</div></div>"
        )

    configured_workflow_names = sorted(
        {w.strip() for w in (configured_workflows or []) if isinstance(w, str) and w.strip()}
    )
    workflow_names = list(configured_workflow_names)
    if selected_default_workflow not in workflow_names:
        workflow_names.insert(0, selected_default_workflow)

    workflow_options_html = "".join(
        (
            f"<option value='{html.escape(name)}'"
            f"{' selected' if name == selected_default_workflow else ''}>"
            f"{html.escape(name)}</option>"
        )
        for name in workflow_names
    )

    workflow_rows_html = "".join(
        (
            "<div class='queue-row'>"
            f"<a href='/workflow/{quote(name)}' style='font-weight:600'>{html.escape(name)}</a>"
            f"<form method='post' action='/workflow/run-now' style='margin-top:6px'>"
            f"<input type='hidden' name='name' value='{html.escape(name)}'>"
            "<input type='hidden' name='next' value='/'>"
            "<button class='rerun-btn' type='submit'>Run now</button>"
            "</form>"
            "</div>"
        )
        for name in workflow_names[:6]
    )
    workflow_more_html = (
        f"<div class='source-meta'>+{len(workflow_names) - 6} more</div>" if len(workflow_names) > 6 else ""
    )
    workflow_error_html = (
        f"<div class='source-meta' style='color:#b02030'>{workflow_load_errors} invalid workflow file(s)</div>"
        if workflow_load_errors
        else ""
    )
    workflows_card_html = f"""
      <div class="queue-box queue-box-workflows">
        <strong>Configured workflows</strong>
        <div class="source-meta">{len(configured_workflow_names)} configured</div>
        <div class="source-meta">Default ingest workflow: {html.escape(selected_default_workflow)}</div>
        {workflow_error_html}
        {workflow_rows_html or "<span class='source-meta'>No workflows found</span>"}
        {workflow_more_html}
        <div class="manage-link"><a href="/workflows">Manage workflows</a></div>
      </div>
    """

    trigger_items: list[dict[str, Any]] = []
    for item in configured_triggers or []:
        if isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            workflow = str(item.get("workflow", "")).strip()
            trigger_type = str(item.get("type", "")).strip()
            enabled = bool(item.get("enabled", True))
            last_seen = str(item.get("last_seen", "")).strip()
            next_run_hint = str(item.get("next_run_hint", "")).strip()
            recent_runs = int(item.get("recent_runs", 0))
            recent_failures = int(item.get("recent_failures", 0))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            name = str(item[0]).strip()
            workflow = str(item[1]).strip()
            trigger_type = ""
            enabled = True
            last_seen = ""
            next_run_hint = ""
            recent_runs = 0
            recent_failures = 0
        else:
            continue
        if not name or not workflow:
            continue
        trigger_items.append(
            {
                "name": name,
                "workflow": workflow,
                "type": trigger_type,
                "enabled": enabled,
                "last_seen": last_seen,
                "next_run_hint": next_run_hint,
                "recent_runs": recent_runs,
                "recent_failures": recent_failures,
            }
        )

    def _render_trigger_row(item: dict[str, Any]) -> str:
        name = str(item["name"])
        workflow = str(item["workflow"])
        enabled = bool(item["enabled"])
        last_seen = str(item["last_seen"])
        next_run_hint = str(item["next_run_hint"])
        recent_runs = int(item["recent_runs"])
        recent_failures = int(item["recent_failures"])
        status_label = "enabled" if enabled else "disabled"
        toggle_target = "0" if enabled else "1"
        toggle_btn_class = "danger-btn" if enabled else "rerun-btn"
        toggle_label = "Disable" if enabled else "Enable"
        last_activity_html = ""
        if last_seen:
            last_activity_html = f"<div class='source-meta'>last activity: {html.escape(last_seen)}</div>"
        next_run_html = ""
        if next_run_hint:
            next_run_html = f"<div class='source-meta'>next run: {html.escape(next_run_hint)}</div>"
        esc_name = html.escape(name)
        return (
            "<div class='queue-row'>"
            f"<a href='/trigger/{quote(name)}' style='font-weight:600'>{esc_name}</a>"
            f"<div class='source-meta'>workflow: {html.escape(workflow)}</div>"
            f"<div class='source-meta'>status: {status_label}</div>"
            f"{last_activity_html}"
            f"{next_run_html}"
            f"<div class='source-meta'>recent jobs: {recent_runs} · failures: {recent_failures}</div>"
            "<div style='display:flex;gap:6px;flex-wrap:wrap;margin-top:6px'>"
            f"<form method='post' action='/trigger/run-now'><input type='hidden' name='name' value='{esc_name}'><input type='hidden' name='next' value='/'><button class='rerun-btn' type='submit'>Run now</button></form>"
            f"<form method='post' action='/trigger/toggle'><input type='hidden' name='name' value='{esc_name}'><input type='hidden' name='enabled' value='{toggle_target}'><input type='hidden' name='next' value='/'><button class='{toggle_btn_class}' type='submit'>{toggle_label}</button></form>"
            "</div>"
            "</div>"
        )

    trigger_rows_html = "".join(_render_trigger_row(item) for item in trigger_items[:6])
    trigger_more_html = (
        f"<div class='source-meta'>+{len(trigger_items) - 6} more</div>" if len(trigger_items) > 6 else ""
    )
    trigger_error_html = (
        f"<div class='source-meta' style='color:#b02030'>{trigger_load_errors} invalid trigger file(s)</div>"
        if trigger_load_errors
        else ""
    )
    triggers_card_html = f"""
      <div class="queue-box queue-box-triggers">
        <strong>Configured triggers</strong>
        <div class="source-meta">{len(trigger_items)} configured</div>
        {trigger_error_html}
        {trigger_rows_html or "<div class='source-meta'>No triggers configured</div>"}
        {trigger_more_html}
        <div class="manage-link"><a href="/triggers">Manage triggers</a></div>
      </div>
    """

    enabled_triggers = sum(1 for item in trigger_items if bool(item["enabled"]))
    disabled_triggers = len(trigger_items) - enabled_triggers
    automation_health_html = f"""
      <div class="queue-box queue-box-triggers">
        <strong>Automation health</strong>
        <div class="source-meta">enabled: {enabled_triggers} · disabled: {disabled_triggers}</div>
        <div class="source-meta">worker: {"running" if (w_status or {}).get("status") == "running" else "stopped"}</div>
      </div>
    """

    workflow_count = len(configured_workflow_names)
    trigger_count = len(trigger_items)
    onboarding_html = ""
    if workflow_count == 0 and trigger_count == 0:
        onboarding_html = """
      <div class="queue-box queue-box-workflows">
        <strong>Get started</strong>
        <div class="source-meta" style="margin-top:6px">No workflows or triggers are configured yet.</div>
        <div class="button-row" style="margin-top:10px">
          <a href="/workflow/new"><button class="rerun-btn" type="button">Create workflow</button></a>
          <a href="/trigger/new"><button class="rerun-btn" type="button">Create trigger</button></a>
        </div>
      </div>
    """

    w_running = (w_status or {}).get("status") == "running"
    w_pid = (w_status or {}).get("pid")
    w_label = "running" if w_running else "stopped"
    if w_running and w_pid:
        w_label = f"running (pid={w_pid})"
    worker_controls_html = f"""
        <div class="worker-controls">
          <div class="source-meta">Worker: <strong>{html.escape(w_label)}</strong></div>
          <div class="button-row">
            <form method="post" action="/worker-start"><button class="rerun-btn" type="submit"{"" if not w_running else " disabled"}>Start</button></form>
            <form method="post" action="/worker-stop"><button class="danger-btn" type="submit"{"" if w_running else " disabled"}>Stop</button></form>
          </div>
        </div>
    """

    ingest_card_html = f"""
      <div class="queue-box queue-box-ingest">
        <strong>Ingest new source</strong>
        <form method="post" action="/ingest-url" class="ingest-form">
          <input type="text" name="url" placeholder="URL (YouTube, audio, ...)" required
                 style="width:100%;margin-top:6px;">
          <div class="ingest-row">
            <select name="workflow">{workflow_options_html}</select>
            <select name="mode">
              <option value="full" selected>full</option>
              <option value="transcript">transcript</option>
              <option value="tldr">tldr</option>
              <option value="outline">outline</option>
              <option value="notes">notes</option>
            </select>
            <select name="format">
              <option value="markdown" selected>markdown</option>
              <option value="text">text</option>
              <option value="json">json</option>
            </select>
            <button class="rerun-btn" type="submit">Queue URL</button>
          </div>
        </form>
        <form method="post" action="/ingest-file" enctype="multipart/form-data" class="ingest-form" style="margin-top:10px;padding-top:10px;border-top:1px solid rgba(130, 178, 219, 0.2);">
          <input type="file" name="file" accept="audio/*,.mp3,.wav,.m4a,.ogg,.flac,.opus,.webm" required
                 style="font-size:.84rem;margin-bottom:6px;">
          <div class="ingest-row">
            <select name="workflow">{workflow_options_html}</select>
            <select name="mode">
              <option value="full" selected>full</option>
              <option value="transcript">transcript</option>
              <option value="tldr">tldr</option>
              <option value="outline">outline</option>
              <option value="notes">notes</option>
            </select>
            <select name="format">
              <option value="markdown" selected>markdown</option>
              <option value="text">text</option>
              <option value="json">json</option>
            </select>
            <button class="rerun-btn" type="submit">Upload &amp; queue</button>
          </div>
        </form>
      </div>
    """

    if workflow_count == 0 and trigger_count == 0:
        hero_title = "Welcome to Solus"
        hero_subtitle = "Create your first workflow and trigger, then enable automation."
    elif trigger_count == 0:
        hero_title = "Workflow Console"
        hero_subtitle = "Run workflows manually and add triggers when you are ready to automate."
    else:
        hero_title = "Automation Console"
        hero_subtitle = "Monitor trigger health, queue activity, and outputs in one place."

    if trigger_count > 0:
        left_cards_html = (
            onboarding_html + automation_health_html + workflows_card_html + triggers_card_html + ingest_card_html
        )
    else:
        left_cards_html = onboarding_html + ingest_card_html + workflows_card_html + triggers_card_html

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>solus results</title>
  <style>
    :root {{
      --bg-0: #07111f;
      --bg-1: #0f223a;
      --bg-2: #123a58;
      --ink: #e7f0fb;
      --muted: #9ab2c9;
      --panel: rgba(6, 18, 33, 0.68);
      --panel-soft: rgba(10, 29, 49, 0.75);
      --border: rgba(130, 178, 219, 0.26);
      --accent: #2eb3ff;
      --accent-strong: #1d8ee6;
      --accent-soft: rgba(46, 179, 255, 0.16);
      --good: #39d49a;
      --warn: #f9bf45;
      --bad: #ef6f6c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font-family: "Space Grotesk", "Manrope", "IBM Plex Sans", sans-serif;
      background:
        radial-gradient(circle at 9% -4%, #1f70a8 0%, transparent 40%),
        radial-gradient(circle at 92% 14%, #175772 0%, transparent 36%),
        linear-gradient(160deg, var(--bg-0), var(--bg-1) 45%, var(--bg-2));
      min-height: 100vh;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image: linear-gradient(rgba(140, 190, 226, 0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(140, 190, 226, 0.04) 1px, transparent 1px);
      background-size: 36px 36px;
      opacity: 0.45;
    }}
    .shell {{
      position: relative;
      z-index: 1;
      max-width: 1500px;
      margin: 0 auto;
      padding: 22px;
      display: grid;
      grid-template-columns: 360px 1fr;
      gap: 20px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 20px;
      backdrop-filter: blur(10px);
      box-shadow: 0 26px 56px rgba(2, 10, 20, 0.4);
    }}
    .left {{
      padding: 18px;
      max-height: calc(100vh - 44px);
      overflow: auto;
      position: sticky;
      top: 18px;
    }}
    .right {{
      padding: 20px;
      min-height: calc(100vh - 44px);
    }}
    .left-head {{
      margin-bottom: 12px;
      padding-bottom: 10px;
      border-bottom: 1px solid rgba(130, 178, 219, 0.22);
    }}
    .eyebrow {{
      margin: 0 0 4px;
      text-transform: uppercase;
      letter-spacing: 0.09em;
      font-size: 0.7rem;
      color: #81d5ff;
      font-weight: 700;
    }}
    h1 {{
      margin: 0 0 5px;
      font-size: 1.45rem;
      letter-spacing: 0.01em;
      font-family: "Sora", "Space Grotesk", "IBM Plex Sans", sans-serif;
    }}
    h2 {{
      margin: 0 0 8px;
      font-size: 1.22rem;
      font-family: "Sora", "Space Grotesk", "IBM Plex Sans", sans-serif;
    }}
    .hero-title {{
      margin: 0 0 5px;
      font-size: 1.5rem;
    }}
    .muted {{ color: var(--muted); margin: 0 0 4px; }}
    .hero {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      padding: 16px 18px;
      border: 1px solid var(--border);
      border-radius: 16px;
      background: linear-gradient(145deg, rgba(20, 52, 86, 0.68), rgba(10, 29, 49, 0.82));
      box-shadow: inset 0 1px 0 rgba(200, 234, 255, 0.08);
    }}
    .hero-stats {{
      display: grid;
      grid-template-columns: repeat(3, minmax(76px, 1fr));
      gap: 8px;
      min-width: 250px;
    }}
    .metric {{
      border: 1px solid rgba(130, 178, 219, 0.22);
      border-radius: 11px;
      padding: 8px 10px;
      background: rgba(7, 23, 40, 0.64);
      text-align: right;
      min-width: 0;
    }}
    .metric span {{
      display: block;
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #9ac8ea;
    }}
    .metric strong {{
      font-size: 1.06rem;
      color: #f3fbff;
    }}
    .metric.pending strong {{ color: #9ee6ff; }}
    .metric.processing strong {{ color: #9ddcff; }}
    .metric.done strong {{ color: #7be7be; }}
    .metric.failed strong {{ color: #ffb2ab; }}
    .metric.dead strong {{ color: #f9dd94; }}
    .content-shell {{
      margin-top: 12px;
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 14px;
      background: linear-gradient(155deg, rgba(10, 28, 47, 0.9), rgba(7, 20, 34, 0.86));
    }}
    .source-info-card {{
      border: 1px solid rgba(130, 178, 219, 0.18);
      border-radius: 12px;
      padding: 12px;
      background: rgba(5, 15, 28, 0.5);
      margin-bottom: 12px;
    }}
    .source-info-card h2 {{
      margin-bottom: 6px;
      font-size: 1.18rem;
    }}
    .source-card {{
      display: block;
      text-decoration: none;
      color: inherit;
      border: 1px solid rgba(130, 178, 219, 0.2);
      border-radius: 13px;
      padding: 12px;
      margin: 9px 0;
      background: rgba(7, 22, 38, 0.58);
      transition: transform .14s ease, border-color .14s ease, background .14s ease, box-shadow .14s ease;
    }}
    .source-card:hover {{
      transform: translateY(-1px) scale(1.003);
      border-color: var(--accent);
      background: rgba(11, 32, 52, 0.78);
      box-shadow: 0 10px 20px rgba(4, 13, 23, 0.4);
    }}
    .source-card.active {{
      border-color: var(--accent);
      background: linear-gradient(145deg, var(--accent-soft), rgba(11, 32, 52, 0.8));
      box-shadow: 0 0 0 1px rgba(46, 179, 255, 0.2);
    }}
    .source-title {{
      font-weight: 700;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .source-meta {{
      color: var(--muted);
      font-size: .84rem;
      margin-top: 3px;
    }}
    .queue-box {{
      margin-top: 14px;
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 12px;
      background: var(--panel-soft);
      box-shadow: inset 0 1px 0 rgba(174, 219, 252, 0.08);
    }}
    .queue-box-status {{
      background: linear-gradient(160deg, rgba(13, 34, 56, 0.76), rgba(8, 25, 42, 0.82));
    }}
    .queue-box-ingest {{
      background: linear-gradient(160deg, rgba(12, 37, 55, 0.8), rgba(8, 24, 39, 0.86));
    }}
    .queue-box-workflows {{
      background: linear-gradient(160deg, rgba(14, 38, 66, 0.78), rgba(11, 29, 48, 0.86));
    }}
    .queue-box-triggers {{
      background: linear-gradient(160deg, rgba(17, 33, 64, 0.78), rgba(11, 24, 46, 0.86));
    }}
    .queue-row {{
      border-top: 1px solid rgba(130, 178, 219, 0.2);
      padding: 8px 0;
      font-size: 0.84rem;
    }}
    .chip {{
      margin-left: 6px;
      font-size: .74rem;
      text-transform: uppercase;
      letter-spacing: .03em;
      color: #84d7ff;
    }}
    .tabs {{
      margin-top: 10px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .tab {{
      text-decoration: none;
      color: #d4e8fa;
      border: 1px solid rgba(130, 178, 219, 0.28);
      padding: 7px 12px;
      border-radius: 999px;
      background: rgba(5, 16, 30, 0.54);
      font-size: 0.9rem;
      transition: border-color .14s ease, background .14s ease, transform .14s ease;
    }}
    .tab:hover {{
      border-color: var(--accent);
      background: rgba(13, 36, 58, 0.84);
      transform: translateY(-1px);
    }}
    .tab span {{
      margin-left: 8px;
      color: var(--muted);
      font-size: .8rem;
    }}
    .tab.active {{
      background: var(--accent-soft);
      border-color: var(--accent);
      font-weight: 700;
      color: #f7fdff;
    }}
    .actions {{
      margin-top: 14px;
      margin-bottom: 10px;
    }}
    .raw-link {{
      text-decoration: none;
      color: #fff;
      background: linear-gradient(145deg, var(--accent), var(--accent-strong));
      border-radius: 10px;
      padding: 8px 13px;
      font-weight: 600;
      font-size: .88rem;
      display: inline-block;
      box-shadow: 0 10px 18px rgba(8, 34, 58, 0.5);
    }}
    .viewer {{
      margin-top: 8px;
      border: 1px solid rgba(130, 178, 219, 0.2);
      border-radius: 12px;
      background: rgba(5, 15, 27, 0.55);
      padding: 15px;
      max-height: calc(100vh - 280px);
      overflow: auto;
    }}
    .markdown h1, .markdown h2, .markdown h3, .markdown h4 {{
      font-family: "Sora", "Space Grotesk", "IBM Plex Sans", sans-serif;
      margin: 12px 0 8px;
      line-height: 1.25;
    }}
    .markdown p {{
      margin: 8px 0;
      line-height: 1.55;
    }}
    .markdown ul {{
      margin: 8px 0 8px 22px;
      padding: 0;
      line-height: 1.5;
    }}
    .markdown li {{
      margin: 4px 0;
    }}
    .markdown code, pre code {{
      font-family: "JetBrains Mono", "Fira Code", "SFMono-Regular", monospace;
      background: rgba(130, 178, 219, 0.18);
      border-radius: 4px;
      padding: 1px 4px;
    }}
    .markdown pre {{
      background: rgba(8, 22, 39, 0.74);
      border: 1px solid rgba(130, 178, 219, 0.22);
      border-radius: 8px;
      padding: 10px;
      overflow: auto;
    }}
    pre {{
      margin: 0;
      font-family: "JetBrains Mono", "Fira Code", "SFMono-Regular", monospace;
      font-size: .9rem;
      white-space: pre-wrap;
      line-height: 1.48;
      word-break: break-word;
    }}
    .action-forms {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 10px;
      margin-bottom: 2px;
      align-items: center;
    }}
    .action-forms form {{
      display: flex;
      gap: 6px;
      align-items: center;
    }}
    input[type="text"],
    input[type="file"],
    select {{
      border: 1px solid rgba(130, 178, 219, 0.35);
      border-radius: 9px;
      padding: 7px 9px;
      font-size: .86rem;
      background: rgba(8, 22, 39, 0.9);
      color: #e7f0fb;
      box-shadow: inset 0 1px 0 rgba(180, 225, 255, 0.08);
    }}
    input[type="text"]::placeholder {{
      color: #95b2cb;
    }}
    input[type="file"] {{
      width: 100%;
      padding: 7px 9px;
    }}
    .danger-btn {{
      background: linear-gradient(145deg, #e15a63, #bb3d45);
      color: #fff;
      border: none;
      border-radius: 9px;
      padding: 7px 12px;
      font-size: .86rem;
      font-weight: 600;
      cursor: pointer;
    }}
    .danger-btn:hover {{ filter: brightness(1.06); }}
    .danger-btn:disabled, .rerun-btn:disabled {{
      opacity: 0.45;
      cursor: not-allowed;
    }}
    .worker-controls {{
      border-top: 1px solid rgba(130, 178, 219, 0.2);
      padding-top: 9px;
      margin-top: 9px;
    }}
    .button-row {{
      display: flex;
      gap: 6px;
      margin-top: 7px;
    }}
    .button-row form {{
      margin: 0;
    }}
    .ingest-row {{
      display: flex;
      gap: 6px;
      margin-top: 8px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .ingest-row select {{
      min-width: 0;
      flex: 1 1 110px;
    }}
    .ingest-row .rerun-btn {{
      flex: 0 0 auto;
      white-space: nowrap;
    }}
    .rerun-btn {{
      background: linear-gradient(145deg, var(--accent), var(--accent-strong));
      color: #fff;
      border: none;
      border-radius: 9px;
      padding: 7px 12px;
      font-size: .86rem;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 8px 15px rgba(6, 26, 43, 0.45);
    }}
    .rerun-btn:hover {{ filter: brightness(1.06); }}
    .manage-link {{
      margin-top: 10px;
      padding-top: 8px;
      border-top: 1px solid rgba(130, 178, 219, 0.2);
    }}
    .manage-link a {{
      color: #99ddff;
      font-weight: 600;
      text-decoration: none;
    }}
    .manage-link a:hover {{
      color: #d7f2ff;
      text-decoration: underline;
    }}
    .sources-wrap {{
      margin-top: 16px;
      border-top: 1px solid rgba(130, 178, 219, 0.2);
      padding-top: 12px;
    }}
    .section-title {{
      margin: 0 0 6px;
      font-size: 0.78rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #8bc9ef;
      font-weight: 700;
    }}
    @media (max-width: 960px) {{
      .shell {{
        grid-template-columns: 1fr;
        padding: 14px;
      }}
      .left {{
        position: static;
        max-height: none;
      }}
      .right {{
        min-height: auto;
        padding: 16px;
      }}
      .hero {{
        flex-direction: column;
      }}
      .hero-stats {{
        width: 100%;
        min-width: 0;
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }}
      .viewer {{
        max-height: none;
      }}
    }}
  </style>
</head>
<body>
  {_build_nav("home")}
  <div class="shell">
    <aside class="panel left">
      <div class="left-head">
        <p class="eyebrow">Realtime workspace</p>
        <h1>solus results</h1>
        <p class="muted">localhost viewer</p>
      </div>
      <div class="queue-box queue-box-status">
        <strong>Recent queue activity</strong>
        {f"<div class='source-meta'>Job filter: workflow={html.escape(workflow_filter)}</div>" if workflow_filter else ""}
        {"".join(recent_job_html) if recent_job_html else "<div class='source-meta'>No queued jobs yet.</div>"}
        {worker_controls_html}
      </div>
      {left_cards_html}
      <div class="sources-wrap">
        <p class="section-title">Cached outputs</p>
        {"".join(source_items_html) if source_items_html else "<p class='muted'>No cached output files yet.</p>"}
      </div>
    </aside>
    <main class="panel right">
      <div class="hero">
        <div>
          <p class="eyebrow">Dashboard</p>
          <h2 class="hero-title">{html.escape(hero_title)}</h2>
          <p class="muted">{html.escape(hero_subtitle)}</p>
        </div>
        <div class="hero-stats">
          <div class="metric pending"><span>pending</span><strong>{queue_status.get("pending", 0)}</strong></div>
          <div class="metric processing"><span>processing</span><strong>{queue_status.get("processing", 0)}</strong></div>
          <div class="metric done"><span>done</span><strong>{queue_status.get("done", 0)}</strong></div>
          <div class="metric failed"><span>failed</span><strong>{queue_status.get("failed", 0)}</strong></div>
          <div class="metric dead"><span>dead letter</span><strong>{queue_status.get("dead_letter", 0)}</strong></div>
        </div>
      </div>
      <section class="content-shell">
        <div class="source-info-card">
          {source_info_html}
          {action_forms_html}
        </div>
        <div class="tabs">{file_tabs_html}</div>
        <div class="actions"><a class="raw-link" href="{raw_link}">Open raw file</a></div>
        <section class="viewer">{file_content}</section>
      </section>
    </main>
  </div>
  {_build_footer()}
</body>
</html>
"""


def _build_nav(active: str) -> str:
    def _item(href: str, label: str, key: str, *, with_badge: bool = False, brand: bool = False) -> str:
        is_active = key == active
        style = (
            "color:#ffffff;text-decoration:none;padding:4px 10px;border-radius:999px;"
            "background:#2d3748;border:1px solid #4a5568;"
            if is_active
            else "color:#a0aec0;text-decoration:none;padding:4px 10px;border-radius:999px;"
        )
        if brand and not is_active:
            style = "color:#e2e8f0;text-decoration:none;font-weight:bold;padding:4px 10px;border-radius:999px;"
        badge = (
            '<span id="pending-badge" style="background:#d69e2e;color:#1a1a2e;border-radius:9px;'
            'padding:1px 7px;font-size:12px;display:none"></span>'
            if with_badge
            else ""
        )
        attrs = f'href="{href}" style="{style}" data-active={"true" if is_active else "false"}'
        if is_active:
            attrs += ' aria-current="page"'
        return f"<a {attrs}>{label}{badge}</a>"

    return (
        '<nav style="background:#1a1a2e;padding:8px 16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">'
        + _item("/", "Solus", "home", brand=True)
        + _item("/workflows", "Workflows", "workflows")
        + _item("/triggers", "Triggers", "triggers")
        + _item("/modules", "Modules", "modules")
        + _item("/history", "History", "history", with_badge=True)
        + _item("/config", "Config", "config")
        + _item("/examples", "Examples", "examples")
        + "</nav>"
    )


_SSE_SCRIPT = """<script>
(function() {
  var es = new EventSource('/events');
  es.onmessage = function(e) {
    try {
      var d = JSON.parse(e.data);
      var badge = document.getElementById('pending-badge');
      if (badge) {
        var p = d.counts && d.counts.pending || 0;
        badge.textContent = p;
        badge.style.display = p > 0 ? 'inline' : 'none';
      }
    } catch(err) {}
  };
})();
</script>"""


def build_workflows_page(workflows: list, errors: list[str]) -> str:
    rows = ""
    for wf in workflows:
        name = html.escape(str(wf.name))
        desc = html.escape(str(wf.description or ""))
        steps = len(wf.steps)
        rows += f"<tr><td><a href='/workflow/{name}'>{name}</a></td><td>{desc}</td><td>{steps}</td></tr>\n"
    err_html = ""
    if errors:
        errs = "".join(f"<li>{html.escape(e)}</li>" for e in errors)
        err_html = f"<div style='color:red'><b>Errors:</b><ul>{errs}</ul></div>"
    return f"""<!DOCTYPE html><html><head><title>Workflows — Solus</title>
<style>body{{font-family:system-ui;background:#0f0f23;color:#e2e8f0;margin:0}}
table{{border-collapse:collapse;width:100%}}th,td{{padding:8px 12px;border-bottom:1px solid #2d3748;text-align:left}}
a{{color:#63b3ed}}input,button{{background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:6px 12px;border-radius:4px}}
</style></head><body>
{_build_nav("workflows")}
<div style="padding:16px">
<h1>Workflows</h1>
{err_html}
<p><a href="/workflow/new"><button>+ New Workflow</button></a></p>
<table><thead><tr><th>Name</th><th>Description</th><th>Steps</th></tr></thead>
<tbody>{rows}</tbody></table>
</div>
{_build_footer()}
{_SSE_SCRIPT}
</body></html>"""


def build_workflow_editor_page(
    name: str,
    yaml_content: str,
    validation_issues: list[str],
    *,
    saved: bool = False,
) -> str:
    esc_name = html.escape(name)
    esc_yaml = html.escape(yaml_content)
    err_html = ""
    if validation_issues:
        errs = "".join(f"<li>{html.escape(e)}</li>" for e in validation_issues)
        err_html = f"<div class='error'><b>Validation errors:</b><ul>{errs}</ul></div>"
    saved_html = "<div class='success'>Workflow saved.</div>" if saved else ""
    is_new = name in ("new", "") or not yaml_content
    hint = ""
    if is_new:
        hint = "<p style='color:#a0aec0;font-size:13px'>Start from an <a href='/examples#workflows'>example template</a> or write your own YAML below.</p>"
    delete_html = ""
    if name and name != "new":
        delete_html = f"""
<form method="POST" action="/workflow/delete" style="display:inline"
      onsubmit="return confirm('Delete workflow {esc_name}? Built-in workflows cannot be deleted.')">
  <input type="hidden" name="name" value="{esc_name}">
  <button type="submit" class="danger">Delete workflow</button>
</form>"""
    return f"""<!DOCTYPE html><html><head><title>{"New Workflow" if name == "new" else "Edit: " + esc_name} — Solus</title>
{_DARK_STYLE}</head><body>
{_build_nav("workflows")}
<div style="padding:16px">
<h1>{"New Workflow" if name in ("new", "") else "Edit Workflow: " + esc_name}</h1>
{saved_html}{err_html}{hint}
<form method="POST" action="/workflow/save">
  <p><label>Name: <input name="name" value="{esc_name if name != "new" else ""}"
     required pattern="[\\w\\-]+" placeholder="my_workflow_name"></label></p>
  <textarea name="yaml" rows="22">{esc_yaml}</textarea>
  <p style="display:flex;gap:8px;align-items:center">
    <button type="submit">Save</button>
    <a href="/workflows">Cancel</a>
    {delete_html}
  </p>
</form>
</div>
{_build_footer()}
</body></html>"""


def build_modules_page(specs: list) -> str:
    rows = ""
    for spec in sorted(specs, key=lambda s: (s.category, s.name)):
        name = html.escape(str(spec.name))
        cat = html.escape(str(spec.category))
        ver = html.escape(str(spec.version))
        desc = html.escape(str(spec.description))
        deps = ", ".join(html.escape(d.name) for d in spec.dependencies) or "-"
        reads = ", ".join(html.escape(r.key) for r in spec.reads) or "-"
        writes = ", ".join(html.escape(w.key) for w in spec.writes) or "-"
        rows += (
            f"<tr><td><code>{name}</code></td><td>{cat}</td><td>{ver}</td>"
            f"<td>{desc}</td><td>{deps}</td><td>{reads}</td><td>{writes}</td></tr>\n"
        )
    return f"""<!DOCTYPE html><html><head><title>Modules — Solus</title>
<style>body{{font-family:system-ui;background:#0f0f23;color:#e2e8f0;margin:0}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{padding:6px 10px;border-bottom:1px solid #2d3748;text-align:left;vertical-align:top}}
th{{background:#1a1a2e}}code{{background:#2d3748;padding:2px 5px;border-radius:3px}}
</style></head><body>
{_build_nav("modules")}
<div style="padding:16px">
<h1>Module Catalog</h1>
<table><thead><tr>
  <th>Name</th><th>Category</th><th>Version</th><th>Description</th>
  <th>Dependencies</th><th>Reads</th><th>Writes</th>
</tr></thead><tbody>{rows}</tbody></table>
</div>
{_build_footer()}
{_SSE_SCRIPT}
</body></html>"""


def build_history_page(jobs: list[dict], *, page: int = 1, total_pages: int = 1) -> str:
    rows = ""
    for job in jobs:
        job_id = html.escape(str(job.get("job_id", "")))
        wf = html.escape(str(job.get("workflow_name", "")))
        status = str(job.get("status", ""))
        color = {
            "done": "#68d391",
            "failed": "#fc8181",
            "dead_letter": "#fc8181",
            "pending": "#d69e2e",
            "processing": "#63b3ed",
        }.get(status, "#a0aec0")
        status_html = f"<span style='color:{color}'>{html.escape(status)}</span>"
        source = html.escape(str(job.get("source", ""))[:80])
        created = html.escape(str(job.get("created_at", ""))[:19])
        retry = str(job.get("retry_count", 0))
        error = html.escape(str(job.get("error", ""))[:100])
        rows += (
            f"<tr><td><code>{job_id}</code></td><td>{wf}</td>"
            f"<td>{status_html}</td><td>{source}</td>"
            f"<td>{created}</td><td>{retry}</td>"
            f"<td style='color:#fc8181;font-size:12px'>{error}</td></tr>\n"
        )
    # Pagination nav
    _page_size = 100
    _start = (page - 1) * _page_size + 1 if jobs else 0
    _end = (page - 1) * _page_size + len(jobs)
    _range_str = f"Showing {_start}–{_end}" if jobs else "No jobs"
    _prev = (
        f"<a href='/history?page={page - 1}' style='color:#63b3ed'>← Prev</a>"
        if page > 1
        else "<span style='color:#4a5568'>← Prev</span>"
    )
    _next = (
        f"<a href='/history?page={page + 1}' style='color:#63b3ed'>Next →</a>"
        if page < total_pages
        else "<span style='color:#4a5568'>Next →</span>"
    )
    _pagination = f"<div style='display:flex;gap:12px;align-items:center;margin-bottom:12px;font-size:13px'>{_prev} <span>Page {page} of {total_pages}</span> {_next} <span style='color:#718096'>{_range_str}</span></div>"
    # Bulk action toolbar
    _toolbar = """<div style="display:flex;gap:8px;margin-bottom:12px">
  <form method="POST" action="/bulk-retry-failed">
    <button type="submit">Retry All Failed</button>
  </form>
  <form method="POST" action="/bulk-clear-dead">
    <button class="danger" type="submit">Clear Dead Letter</button>
  </form>
</div>"""
    return f"""<!DOCTYPE html><html><head><title>History — Solus</title>
<style>body{{font-family:system-ui;background:#0f0f23;color:#e2e8f0;margin:0}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{padding:6px 10px;border-bottom:1px solid #2d3748;text-align:left}}
th{{background:#1a1a2e}}code{{background:#2d3748;padding:2px 5px;border-radius:3px}}
button{{background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:6px 12px;
  border-radius:4px;font-size:13px;cursor:pointer}}
button:hover{{background:#4a5568}}
button.danger{{background:#c53030;border-color:#c53030}}
button.danger:hover{{background:#9b2c2c}}
</style></head><body>
{_build_nav("history")}
<div style="padding:16px">
<h1>Job History</h1>
{_toolbar}
{_pagination}
<table><thead><tr>
  <th>Job ID</th><th>Workflow</th><th>Status</th><th>Source</th>
  <th>Created</th><th>Retries</th><th>Error</th>
</tr></thead><tbody>{rows}</tbody></table>
{_pagination}
</div>
{_build_footer()}
{_SSE_SCRIPT}
</body></html>"""


def build_sse_script() -> str:
    return _SSE_SCRIPT


# ---------------------------------------------------------------------------
# Shared style block for the dark-theme admin pages
# ---------------------------------------------------------------------------
_DARK_STYLE = """<style>
body{font-family:system-ui;background:#0f0f23;color:#e2e8f0;margin:0}
table{border-collapse:collapse;width:100%}
th,td{padding:8px 12px;border-bottom:1px solid #2d3748;text-align:left;vertical-align:top}
th{background:#1a1a2e}
a{color:#63b3ed}
input,button,select{background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;
  padding:6px 12px;border-radius:4px;font-size:14px}
button{cursor:pointer}
button:hover{background:#4a5568}
button.danger{background:#c53030;border-color:#c53030}
button.danger:hover{background:#9b2c2c}
textarea{width:100%;background:#1a1a2e;color:#e2e8f0;border:1px solid #4a5568;
  font-family:monospace;font-size:13px;padding:8px;box-sizing:border-box;
  border-radius:4px;resize:vertical}
.notice{background:#2d3748;border-left:4px solid #d69e2e;padding:10px 14px;
  margin:12px 0;border-radius:0 4px 4px 0;font-size:13px;color:#fbd38d}
.error{background:#2d3748;border-left:4px solid #fc8181;padding:10px 14px;
  margin:12px 0;border-radius:0 4px 4px 0;color:#fc8181}
.success{background:#2d3748;border-left:4px solid #68d391;padding:10px 14px;
  margin:12px 0;border-radius:0 4px 4px 0;color:#68d391}
.card{background:#1a1a2e;border:1px solid #2d3748;border-radius:8px;
  padding:16px;margin:12px 0}
.card h3{margin:0 0 6px;color:#e2e8f0}
.card p{margin:4px 0;color:#a0aec0;font-size:13px}
.card .actions{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap}
.tag{display:inline-block;background:#2d3748;border-radius:4px;
  padding:2px 7px;font-size:12px;color:#a0aec0;font-family:monospace}
.template-section{margin-top:20px;padding:16px;border:1px solid #2d3748;border-radius:12px;background:#141634}
.template-section.workflows{box-shadow:inset 0 0 0 1px rgba(99,179,237,.18)}
.template-section.triggers{box-shadow:inset 0 0 0 1px rgba(214,158,46,.22)}
.template-section h2{margin:0 0 6px}
.template-section .section-lead{margin:0;color:#a0aec0;font-size:13px}
.template-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px;margin-top:12px}
.section-split{height:1px;margin:22px 0;background:linear-gradient(90deg,transparent,#374151,transparent)}
.template-section.workflows .card{background:#16233a;border-color:#2b4f73}
.template-section.workflows .card h3{color:#b6dcff}
.template-section.workflows .card p{color:#c7d9ea}
.template-section.workflows .card pre{background:#0f1b2d;border-color:#2b4f73}
.template-section.triggers .card{background:#3b2718;border-color:#6f4a22}
.template-section.triggers .card h3{color:#ffd8a8}
.template-section.triggers .card p{color:#f3d7b0}
.template-section.triggers .card pre{background:#2e1f12;border-color:#6f4a22}
</style>"""


# ---------------------------------------------------------------------------
# Triggers pages
# ---------------------------------------------------------------------------


def build_triggers_page(triggers: list, errors: list[str]) -> str:
    rows = ""
    for t in triggers:
        name = html.escape(str(t.name))
        ttype = html.escape(str(t.type))
        workflow = html.escape(str(t.workflow))
        enabled = bool(getattr(t, "enabled", True))
        status = "enabled" if enabled else "disabled"
        toggle_target = "0" if enabled else "1"
        toggle_label = "Disable" if enabled else "Enable"
        rows += (
            f"<tr>"
            f"<td><a href='/trigger/{name}'>{name}</a></td>"
            f"<td><span class='tag'>{ttype}</span></td>"
            f"<td>{workflow}</td>"
            f"<td>{status}</td>"
            "<td style='display:flex;gap:6px;flex-wrap:wrap'>"
            f"<form method='POST' action='/trigger/run-now'><input type='hidden' name='name' value='{name}'><input type='hidden' name='next' value='/triggers'><button type='submit'>Run now</button></form>"
            f"<form method='POST' action='/trigger/toggle'><input type='hidden' name='name' value='{name}'><input type='hidden' name='enabled' value='{toggle_target}'><input type='hidden' name='next' value='/triggers'><button type='submit'>{toggle_label}</button></form>"
            "</td>"
            f"</tr>\n"
        )
    err_html = ""
    if errors:
        errs = "".join(f"<li>{html.escape(e)}</li>" for e in errors)
        err_html = f"<div class='error'><b>Parse errors:</b><ul>{errs}</ul></div>"
    return f"""<!DOCTYPE html><html><head><title>Triggers — Solus</title>
{_DARK_STYLE}</head><body>
{_build_nav("triggers")}
<div style="padding:16px">
<h1>Triggers</h1>
<div class='notice'>
  <div><strong>Apply trigger changes</strong> by restarting the worker.</div>
  <form method="POST" action="/worker-restart" style="margin-top:8px">
    <input type="hidden" name="next" value="/triggers">
    <button type="submit">Restart Worker</button>
  </form>
</div>
{err_html}
<p><a href="/trigger/new"><button>+ New Trigger</button></a>
   <a href="/examples#triggers" style="margin-left:8px"><button>Browse Examples</button></a></p>
<table><thead><tr><th>Name</th><th>Type</th><th>Workflow</th><th>Status</th><th>Actions</th></tr></thead>
<tbody>{rows or "<tr><td colspan='5' style='color:#a0aec0'>No triggers found.</td></tr>"}</tbody>
</table>
</div>
{_build_footer()}
{_SSE_SCRIPT}
</body></html>"""


def build_trigger_editor_page(
    name: str,
    yaml_content: str,
    validation_issues: list[str],
    *,
    saved: bool = False,
) -> str:
    esc_name = html.escape(name)
    esc_yaml = html.escape(yaml_content)
    err_html = ""
    if validation_issues:
        errs = "".join(f"<li>{html.escape(e)}</li>" for e in validation_issues)
        err_html = f"<div class='error'><b>Validation errors:</b><ul>{errs}</ul></div>"
    saved_html = "<div class='success'>Saved. Use Restart Worker to apply trigger changes.</div>" if saved else ""
    is_new = not yaml_content or name in ("new", "")
    hint = ""
    if is_new:
        hint = "<p style='color:#a0aec0;font-size:13px'>Start from an <a href='/examples#triggers'>example template</a> or write your own YAML below.</p>"
    delete_html = ""
    if name and name != "new":
        delete_html = f"""
<form method="POST" action="/trigger/delete" style="display:inline"
      onsubmit="return confirm('Delete trigger {esc_name}?')">
  <input type="hidden" name="name" value="{esc_name}">
  <button type="submit" class="danger">Delete trigger</button>
</form>"""
    return f"""<!DOCTYPE html><html><head><title>{"New Trigger" if name == "new" else "Edit: " + esc_name} — Solus</title>
{_DARK_STYLE}</head><body>
{_build_nav("triggers")}
<div style="padding:16px">
<h1>{"New Trigger" if name in ("new", "") else "Edit Trigger: " + esc_name}</h1>
<div class='notice'>
  <div><strong>Apply trigger changes</strong> by restarting the worker.</div>
  <form method="POST" action="/worker-restart" style="margin-top:8px">
    <input type="hidden" name="next" value="/trigger/{esc_name if name not in ("new", "") else "new"}">
    <button type="submit">Restart Worker</button>
  </form>
</div>
{saved_html}{err_html}{hint}
<form method="POST" action="/trigger/save">
  <p><label>Name: <input name="name" value="{esc_name if name != "new" else ""}"
     required pattern="[\\w\\-]+" placeholder="my_trigger_name"></label></p>
  <textarea name="yaml" rows="22">{esc_yaml}</textarea>
  <p style="display:flex;gap:8px;align-items:center">
    <button type="submit">Save</button>
    <a href="/triggers">Cancel</a>
    {delete_html}
  </p>
</form>
</div>
{_build_footer()}
</body></html>"""


# ---------------------------------------------------------------------------
# Config editor page
# ---------------------------------------------------------------------------


def build_config_editor_page(
    config_path: str,
    toml_content: str,
    *,
    saved: bool = False,
    error: str = "",
) -> str:
    esc_path = html.escape(config_path)
    esc_toml = html.escape(toml_content)
    saved_html = (
        "<div class='success'>Saved. Restart <code>solus serve</code> for changes to take effect.</div>"
        if saved
        else ""
    )
    err_html = f"<div class='error'>{html.escape(error)}</div>" if error else ""
    return f"""<!DOCTYPE html><html><head><title>Config — Solus</title>
{_DARK_STYLE}</head><body>
{_build_nav("config")}
<div style="padding:16px">
<h1>Configuration</h1>
<p style="color:#a0aec0;font-size:13px">File: <code>{esc_path}</code>
  &nbsp;·&nbsp; CLI: <code>solus config</code> · <code>solus config edit</code></p>
<div class='notice'><strong>Config changes require a server restart</strong> to take effect.
  Stop and re-run <code>solus serve</code> after saving.</div>
{saved_html}{err_html}
<form method="POST" action="/config/save">
  <textarea name="toml" rows="36">{esc_toml}</textarea>
  <p><button type="submit">Save</button>
     <a href="/config" style="margin-left:8px">Discard changes</a></p>
</form>
</div>
{_build_footer()}
</body></html>"""


# ---------------------------------------------------------------------------
# Examples / templates browser
# ---------------------------------------------------------------------------


def build_examples_page(workflow_examples: list[dict], trigger_examples: list[dict]) -> str:
    def _cards(examples: list[dict], editor_prefix: str) -> str:
        out = []
        for ex in examples:
            name = html.escape(ex["name"])
            title = html.escape(ex["title"])
            desc = html.escape(ex["description"])
            yaml_preview = html.escape(ex["yaml"][:300] + ("…" if len(ex["yaml"]) > 300 else ""))
            out.append(f"""
<div class='card'>
  <h3>{title}</h3>
  <p>{desc}</p>
  <pre style="background:#0f0f23;border:1px solid #2d3748;border-radius:4px;
    padding:10px;font-size:12px;overflow:auto;max-height:160px;margin:8px 0">{yaml_preview}</pre>
  <div class='actions'>
    <a href="/{editor_prefix}/new?template={name}"><button>Use as template</button></a>
  </div>
</div>""")
        return "\n".join(out)

    wf_cards = _cards(workflow_examples, "workflow")
    tr_cards = _cards(trigger_examples, "trigger")

    return f"""<!DOCTYPE html><html><head><title>Examples — Solus</title>
{_DARK_STYLE}</head><body>
{_build_nav("examples")}
<div style="padding:16px">
<h1>Examples &amp; Templates</h1>
<p style="color:#a0aec0">Click <em>Use as template</em> to pre-fill the editor.
  CLI equivalents: <code>solus workflows examples</code> · <code>solus triggers examples</code></p>
<p style="color:#a0aec0;font-size:13px;margin-top:8px">
  Jump to: <a href="#workflows">Workflow templates</a> · <a href="#triggers">Trigger templates</a>
</p>

<section id="workflows" class="template-section workflows">
  <h2>Workflow Templates</h2>
  <p class="section-lead">Reusable workflow skeletons for ingestion, transformation, and output pipelines.</p>
  <div class="template-grid">{wf_cards or "<div class='card'><p>No workflow templates available.</p></div>"}</div>
</section>

<div class="section-split"></div>

<section id="triggers" class="template-section triggers">
  <h2>Trigger Templates</h2>
  <p class="section-lead">Event and schedule templates that enqueue workflows automatically.</p>
  <div class="template-grid">{tr_cards or "<div class='card'><p>No trigger templates available.</p></div>"}</div>
</section>
</div>
{_build_footer()}
{_SSE_SCRIPT}
</body></html>"""
