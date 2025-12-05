import yaml
import os

CONFIG_PATH = "core_configuration.yml"

def load_core_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"core_configuration.yml missing at {CONFIG_PATH}")

    with open(CONFIG_PATH, "r") as config_file:
        return yaml.safe_load(config_file)