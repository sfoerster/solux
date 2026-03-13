"""EmailPollTrigger — polls an IMAP mailbox for unseen messages."""

from __future__ import annotations

import email as _email_mod
import imaplib
import logging
import threading
from pathlib import Path

from ..queueing import enqueue_jobs
from .spec import Trigger
from ._state import _state_db, _is_seen, _mark_seen

logger = logging.getLogger(__name__)


class EmailPollTrigger:
    def __init__(
        self,
        trigger: Trigger,
        cache_dir: Path,
        state_db_path: Path,
        stop_event: threading.Event,
    ) -> None:
        self.trigger = trigger
        self.cache_dir = cache_dir
        self.state_db_path = state_db_path
        self.stop_event = stop_event

    def run(self) -> None:
        cfg = self.trigger.config
        host = str(cfg.get("host", ""))
        port = int(cfg.get("port", 993))
        username = str(cfg.get("username", ""))
        password = str(cfg.get("password", ""))
        folder = str(cfg.get("folder", "INBOX"))
        interval = float(cfg.get("interval_seconds", 300))
        trigger_name = self.trigger.name

        if not host or not username or not password:
            logger.error("trigger[%s]: email_poll requires host, username, password", trigger_name)
            return

        conn = _state_db(self.state_db_path)
        logger.info(
            "trigger[%s]: polling IMAP %s@%s/%s every %.1fs",
            trigger_name,
            username,
            host,
            folder,
            interval,
        )
        try:
            while not self.stop_event.is_set():
                try:
                    imap = imaplib.IMAP4_SSL(host, port)
                    imap.login(username, password)
                    imap.select(folder)
                    status, data = imap.search(None, "UNSEEN")
                    if status == "OK" and data[0]:
                        for uid in data[0].split():
                            uid_str = uid.decode("ascii")
                            key = f"uid:{uid_str}"
                            if not _is_seen(conn, trigger_name, key):
                                status2, msg_data = imap.fetch(uid, "(RFC822)")
                                msg_dict = {"uid": uid_str}
                                if status2 == "OK" and msg_data and isinstance(msg_data[0], tuple):
                                    msg = _email_mod.message_from_bytes(msg_data[0][1])
                                    msg_dict["subject"] = str(msg.get("Subject", ""))
                                    msg_dict["from"] = str(msg.get("From", ""))
                                    msg_dict["date"] = str(msg.get("Date", ""))
                                logger.info("trigger[%s]: new email uid=%s", trigger_name, uid_str)
                                try:
                                    params = {
                                        **dict(self.trigger.params),
                                        **msg_dict,
                                        "_trigger_name": trigger_name,
                                        "_trigger_type": self.trigger.type,
                                    }
                                    enqueue_jobs(
                                        self.cache_dir,
                                        sources=[f"email://{host}/{folder}/{uid_str}"],
                                        workflow_name=self.trigger.workflow,
                                        params=params,
                                    )
                                    # At-least-once by default: only mark as seen after enqueue succeeds.
                                    _mark_seen(conn, trigger_name, key)
                                except Exception as exc:
                                    logger.warning("trigger[%s]: enqueue failed: %s", trigger_name, exc)
                    imap.logout()
                except imaplib.IMAP4.error as exc:
                    logger.warning("trigger[%s]: IMAP error: %s", trigger_name, exc)
                except Exception as exc:
                    logger.warning("trigger[%s]: unexpected error: %s", trigger_name, exc)
                self.stop_event.wait(timeout=interval)
        finally:
            conn.close()
