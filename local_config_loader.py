#!/usr/bin/env python3
# Local module to support yaml based configuration.
[__all__] = ["load_core_config"]
import yaml
import os

CONFIG_PATH = "./my_data/core_configuration.yml"

def load_core_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"core_configuration.yml missing at {CONFIG_PATH}")

    with open(CONFIG_PATH, "r") as config_file:
        return yaml.safe_load(config_file)