import json
from .config import atomic_json, data_root, offline_uuid, validate_name


class Profiles:
    def __init__(self, settings):
        self.settings = settings
        self.path = data_root() / "profiles.json"
        data = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.records = data.get("profiles", [])
        self.controllers = data.get("controllers", {})
        if not self.records and settings.account_mode == "local":
            self.records = [self.local_profile(f"Player{i}") for i in range(1, 5)]
        self.refresh()

    @staticmethod
    def local_profile(name):
        validate_name(name)
        return {"name": name, "kind": "local", "id": offline_uuid(name).hex}

    def refresh(self):
        if self.settings.account_mode == "microsoft":
            from .prism import accounts

            microsoft = accounts()
            self.records = [
                p for p in self.records if p["kind"] != "microsoft"
            ] + microsoft
        self.save()

    def visible(self):
        return [p for p in self.records if p["kind"] == self.settings.account_mode]

    def add_local(self, name):
        if self.settings.account_mode != "local":
            raise ValueError("Add Microsoft accounts in Prism Launcher.")
        if any(p["name"].lower() == name.lower() for p in self.visible()):
            raise ValueError("That profile already exists.")
        record = self.local_profile(name)
        self.records.append(record)
        self.save()
        return record

    def get(self, name):
        return next(p for p in self.visible() if p["name"] == name)

    def save(self):
        # No provider tokens are accepted in this file.
        safe = [{k: p[k] for k in ["name", "kind", "id"]} for p in self.records]
        atomic_json(self.path, {"profiles": safe, "controllers": self.controllers})
