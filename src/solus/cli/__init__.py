from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .parser import build_parser
from .run import cmd_run
from .workflows import (
    cmd_workflows_list,
    cmd_workflows_show,
    cmd_workflows_validate,
    cmd_workflows_delete,
    cmd_workflows_examples,
)
from .modules import cmd_modules_list, cmd_modules_inspect
from .queue import cmd_ingest, cmd_log
from .init import cmd_init
from .maintenance import cmd_doctor, cmd_config, cmd_config_edit, cmd_cleanup, cmd_retry, cmd_repair
from .server import cmd_serve
from .worker_cmd import cmd_worker
from .triggers import (
    cmd_triggers_list,
    cmd_triggers_show,
    cmd_triggers_validate,
    cmd_triggers_delete,
    cmd_triggers_examples,
)

# Backwards-compatible aliases used by tests
run_ingest_command = cmd_ingest
run_log_command = cmd_log
run_repair_command = cmd_repair
run_workflows_list_command = cmd_workflows_list
run_modules_list_command = cmd_modules_list


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    argv_list = list(argv) if argv is not None else list(sys.argv[1:])
    commands = {
        "run",
        "workflows",
        "modules",
        "ingest",
        "init",
        "doctor",
        "config",
        "cleanup",
        "log",
        "serve",
        "retry",
        "repair",
        "worker",
        "triggers",
        "examples",
        "-h",
        "--help",
    }
    if argv_list and argv_list[0] not in commands:
        argv_list.insert(0, "run")
    args = build_parser().parse_args(argv_list)
    if getattr(args, "command", None) == "worker" and getattr(args, "worker_action", None) is None:
        args.worker_action = "status"
    if getattr(args, "command", None) == "workflows" and getattr(args, "workflows_action", None) is None:
        args.workflows_action = "list"
    if getattr(args, "command", None) == "modules" and getattr(args, "modules_action", None) is None:
        args.modules_action = "list"
    if getattr(args, "command", None) == "triggers" and getattr(args, "triggers_action", None) is None:
        args.triggers_action = "list"
    if getattr(args, "command", None) == "config" and getattr(args, "config_action", None) is None:
        args.config_action = "show"
    return args


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if not raw_argv:
        build_parser().print_help()
        return 1

    args = parse_args(raw_argv)
    if args.command == "init":
        return cmd_init(args)
    if args.command == "examples":
        return cmd_workflows_examples()
    if args.command == "doctor":
        return cmd_doctor(args)
    if args.command == "config":
        if getattr(args, "config_action", "show") == "edit":
            return cmd_config_edit()
        return cmd_config()
    if args.command == "cleanup":
        return cmd_cleanup(args)
    if args.command == "workflows":
        if args.workflows_action == "show":
            return cmd_workflows_show(args.name)
        if args.workflows_action == "validate":
            return cmd_workflows_validate(args.name)
        if args.workflows_action == "delete":
            return cmd_workflows_delete(args.name, yes=getattr(args, "yes", False))
        if args.workflows_action == "examples":
            return cmd_workflows_examples()
        return cmd_workflows_list()
    if args.command == "triggers":
        if args.triggers_action == "show":
            return cmd_triggers_show(args.name)
        if args.triggers_action == "validate":
            return cmd_triggers_validate(args.name)
        if args.triggers_action == "delete":
            return cmd_triggers_delete(args.name, yes=getattr(args, "yes", False))
        if args.triggers_action == "examples":
            return cmd_triggers_examples()
        return cmd_triggers_list()
    if args.command == "modules":
        if args.modules_action == "inspect":
            return cmd_modules_inspect(args.name)
        return cmd_modules_list()
    if args.command == "ingest":
        return cmd_ingest(args)
    if args.command == "log":
        return cmd_log(args)
    if args.command == "serve":
        return cmd_serve(args)
    if args.command == "retry":
        return cmd_retry(args)
    if args.command == "repair":
        return cmd_repair()
    if args.command == "worker":
        return cmd_worker(args)

    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
