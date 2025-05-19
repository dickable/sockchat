class JSONValidator:
    """
    Validate JSON data against a schema.
    Schema example:
    {
        "host": {"type": str, "required": True},
        "port": {"type": int, "required": True},
        "options": {
            "type": dict,
            "required": False,
            "schema": {
                "debug": {"type": bool, "required": False}
            }
        }
    }
    """

    def __init__(self, schema):
        self.schema = schema
        self.errors = []

    def validate(self, data):
        self.errors.clear()
        self._validate_dict(data, self.schema, path="")
        return len(self.errors) == 0

    def _validate_dict(self, data, schema, path):
        if not isinstance(data, dict):
            self.errors.append(f"{path or 'root'} is not a dict")
            return

        for key, rules in schema.items():
            full_key = f"{path}.{key}" if path else key

            if rules.get("required", False) and key not in data:
                self.errors.append(f"Missing required key: '{full_key}'")
                continue

            if key in data:
                value = data[key]
                expected_type = rules.get("type")
                if expected_type and not isinstance(value, expected_type):
                    self.errors.append(f"Key '{full_key}' expected type {expected_type.__name__}, got {type(value).__name__}")
                    continue

                # If nested schema provided, recurse
                if expected_type == dict and "schema" in rules:
                    self._validate_dict(value, rules["schema"], full_key)

                # If list type with schema
                if expected_type == list and "schema" in rules:
                    if not isinstance(value, list):
                        self.errors.append(f"Key '{full_key}' expected list, got {type(value).__name__}")
                        continue
                    for idx, item in enumerate(value):
                        self._validate_dict(item, rules["schema"], f"{full_key}[{idx}]")

    def get_errors(self):
        return self.errors
