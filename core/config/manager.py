import json
import os
import logging
from core.config.validator import JSONValidator

class ConfigManager:
    def __init__(self, path="assets/config.json", default=None):
        self.path = path
        self.default = default or {
            "host": "0.0.0.0",
            "port": 12345
        }
        self.schema = {
            "host": {"type": str, "required": True},
            "port": {"type": int, "required": True}
        }
        self.validator = JSONValidator(self.schema)
        self.config = {}
        self.load()

    def load(self):
        import os, json, logging
        if not os.path.exists(self.path):
            logging.warning(f"Config file '{self.path}' not found. Using default config.")
            self.config = self.default
            return
        try:
            with open(self.path, 'r') as f:
                data = json.load(f)
            if self.validator.validate(data):
                self.config = data
            else:
                logging.error("Config validation failed:\n" + "\n".join(self.validator.get_errors()))
                self.config = self.default
        except (json.JSONDecodeError, IOError) as e:
            logging.error(f"Failed to load config: {e}. Using default config.")
            self.config = self.default

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, 'w') as f:
                json.dump(self.config, f, indent=4)
            logging.info(f"Config saved to '{self.path}'.")
        except IOError as e:
            logging.error(f"Failed to save config: {e}.")

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
        self.save()
