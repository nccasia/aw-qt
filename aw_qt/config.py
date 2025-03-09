from typing import List, Any

from aw_core.config import load_config_toml


default_config = """
[aw-qt]
autostart_modules = ["aw-watcher-afk", "aw-watcher-window"]
oauth2_auth_url = "https://oauth2.mezon.ai"
oauth2_client_id = "1840672452439445504"
oauth2_redirect_uri = "https://tracker-api.komu.vn/api/0/auth/callback"
application_domain = "tracker.komu.vn"

[aw-qt-testing]
autostart_modules = ["aw-watcher-afk", "aw-watcher-window"]
""".strip()


class AwQtSettings:
    def __init__(self, testing: bool):
        """
        An instance of loaded settings, containing a list of modules to autostart.
        Constructor takes a `testing` boolean as an argument
        """
        config = load_config_toml("aw-qt", default_config)
        config_section: Any = config["aw-qt" if not testing else "aw-qt-testing"]

        self.autostart_modules: List[str] = config_section["autostart_modules"]
        self.oauth2_auth_url = config_section["oauth2_auth_url"]
        self.oauth2_client_id = config_section["oauth2_client_id"]
        self.oauth2_redirect_uri = config_section["oauth2_redirect_uri"]
        self.application_domain = config_section["application_domain"]
