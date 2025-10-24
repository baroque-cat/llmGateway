# src/services/config_manager.py

import os
import re
import sys
import copy
import secrets
from typing import List, Tuple, Dict, Any

from ruamel.yaml import YAML

from src.config.defaults import get_default_config
from src.config.provider_templates import PROVIDER_TYPE_DEFAULTS

class ConfigManager:
    """
    A service class to manage the providers.yaml configuration file programmatically.
    It handles creation, deletion, and listing of provider instances.
    This class works directly with the YAML file structure.
    """
    def __init__(
        self,
        config_path: str = "config/providers.yaml",
        env_path: str = ".env",
        keys_base_path: str = "keys",
        proxies_base_path: str = "proxies",
    ):
        self.config_path = config_path
        self.env_path = env_path
        self.keys_base_path = keys_base_path
        self.proxies_base_path = proxies_base_path
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.indent(mapping=2, sequence=4, offset=2)
        self.name_validation_pattern = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9_-]*[a-zA-Z0-9])?$")

    def _load_config(self) -> Dict[str, Any]:
        """Loads the YAML config or creates a base structure if it doesn't exist."""
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                # Handle empty file case
                return self.yaml.load(f) or {}
        else:
            print(f"Configuration file not found at '{self.config_path}'. A new one will be created.")
            default_conf = get_default_config()
            # Start with an empty provider list as planned
            default_conf['providers'] = {}
            return default_conf

    def _save_config(self, config_data: Dict[str, Any]):
        """Saves the configuration data back to the YAML file."""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                self.yaml.dump(config_data, f)
        except PermissionError:
            print(f"Error: Permission denied to write to '{self.config_path}'.", file=sys.stderr)
            sys.exit(1)

    def _validate_instance_name(self, name: str):
        """Validates the instance name."""
        if not self.name_validation_pattern.match(name):
            raise ValueError(
                f"Invalid instance name '{name}'. Names must use letters, numbers, underscores, or hyphens, "
                "and cannot start or end with a hyphen or underscore."
            )

    def _parse_provider_arg(self, provider_arg: str) -> Tuple[str, List[str]]:
        """Parses a command-line argument like 'gemini:name1,name2'."""
        if ':' not in provider_arg or provider_arg.count(':') > 1:
            raise ValueError(f"Invalid format: '{provider_arg}'. Expected 'type:name1,name2'")
        
        provider_type, names_str = provider_arg.split(':', 1)
        if not provider_type or not names_str:
            raise ValueError("Provider type and at least one instance name are required.")
        
        provider_names = [name.strip() for name in names_str.split(',')]
        if not all(provider_names):
            raise ValueError("Instance names cannot be empty.")
        
        return provider_type, provider_names

    def _build_new_instance(self, provider_type: str, instance_name: str, full: bool) -> Dict[str, Any]:
        """
        Constructs the configuration dictionary for a new provider instance.
        This method has been refactored to ensure a logical key order in the output YAML.
        """
        # Step 1: Check if the provider type is supported.
        if provider_type not in PROVIDER_TYPE_DEFAULTS:
            supported = ", ".join(PROVIDER_TYPE_DEFAULTS.keys())
            raise ValueError(f"Unsupported provider type '{provider_type}'. Supported: {supported}")

        # Step 2: Prepare common customizations.
        token_var_name = f"{instance_name.upper().replace('-', '_')}_TOKEN"
        custom_fields = {
            'provider_type': provider_type,
            'keys_path': os.path.join(self.keys_base_path, instance_name, ''),
            'access_control': {
                'gateway_access_token': f"${{{token_var_name}}}"
            }
        }

        # Step 3: Build the config based on the 'full' flag.
        if full:
            # For a full config, we merge multiple layers.
            # 1. Start with the absolute base template.
            full_instance_config = copy.deepcopy(get_default_config()['providers']['llm_provider_default'])
            
            # 2. Merge the provider-specific template over it.
            type_specifics = PROVIDER_TYPE_DEFAULTS[provider_type]
            full_instance_config.update(type_specifics)

            # 3. Apply the final instance-specific customizations.
            full_instance_config.update(custom_fields)
            full_instance_config['proxy_config']['pool_list_path'] = os.path.join(self.proxies_base_path, instance_name, '')
            
            return full_instance_config
        else:
            # --- REFACTORED LOGIC FOR MINIMAL CONFIG ---
            # This logic is designed to create a clean, minimal config with a logical key order.
            
            # 1. Create an empty dictionary to control insertion order. This is the core of the fix.
            minimal_config = {}

            # 2. Add the most important identifying keys first, ensuring they appear at the top of the YAML block.
            minimal_config["provider_type"] = provider_type
            minimal_config["enabled"] = True
            
            # 3. Merge the provider-specific template. This adds all relevant defaults
            #    (like api_base_url, default_model, models, shared_key_status) in a robust way.
            type_specifics = copy.deepcopy(PROVIDER_TYPE_DEFAULTS[provider_type])
            minimal_config.update(type_specifics)
            
            # 4. Add the final instance-specific fields to the end.
            minimal_config["keys_path"] = custom_fields["keys_path"]
            minimal_config["access_control"] = custom_fields["access_control"]
            
            return minimal_config

    def _create_related_directories(self, instance_config: Dict[str, Any]):
        """Creates directories based on the generated instance config."""
        # Always create the keys directory
        os.makedirs(instance_config['keys_path'], exist_ok=True)
        print(f"Ensured directory exists: '{instance_config['keys_path']}'")
        
        # Only create the proxies directory if the mode requires it.
        # This implements the planned improvement for cleaner file systems.
        proxy_mode = instance_config.get('proxy_config', {}).get('mode', 'none')
        if proxy_mode == 'stealth':
            proxy_path = instance_config['proxy_config']['pool_list_path']
            os.makedirs(proxy_path, exist_ok=True)
            print(f"Ensured directory exists: '{proxy_path}'")

    def _update_env_file(self, vars_to_add: List[str]):
        """Creates or updates the .env file without overwriting existing vars."""
        if not vars_to_add: return
        existing_vars = set()
        if os.path.exists(self.env_path):
            with open(self.env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    match = re.match(r'^\s*([a-zA-Z0-9_]+)=', line)
                    if match: existing_vars.add(match.group(1))
        
        new_vars = [v for v in vars_to_add if v.split('=', 1)[0] not in existing_vars]
        if new_vars:
            try:
                with open(self.env_path, 'a', encoding='utf-8') as f:
                    if os.path.getsize(self.env_path) > 0 and f.tell() > 0: f.write("\n")
                    f.write("# Added by llmGateway config manager\n")
                    f.write("\n".join(new_vars) + "\n")
                print(f"Updated '{self.env_path}' with {len(new_vars)} new variable(s).")
            except PermissionError:
                print(f"Warning: Could not write to '{self.env_path}'. Please add manually:", file=sys.stderr)
                for var in new_vars: print(f"  {var}", file=sys.stderr)

    def create_instances(self, provider_args: List[str], full: bool = False):
        """Public method to create provider instances (minimal or full)."""
        config = self._load_config()
        env_vars = []
        count = 0
        for arg in provider_args:
            try:
                provider_type, names = self._parse_provider_arg(arg)
                for name in names:
                    self._validate_instance_name(name)
                    if 'providers' in config and name in config['providers']:
                        print(f"Warning: Instance '{name}' already exists. Skipping.")
                        continue
                    
                    print(f"Creating instance '{name}' (type: {provider_type}, mode: {'full' if full else 'minimal'})...")
                    instance_conf = self._build_new_instance(provider_type, name, full)
                    
                    if 'providers' not in config: config['providers'] = {}
                    config['providers'][name] = instance_conf
                    
                    # We need the full config to decide on directories, even for minimal mode
                    full_conf_for_dirs = self._build_new_instance(provider_type, name, True)
                    self._create_related_directories(full_conf_for_dirs)
                    
                    token_var = instance_conf['access_control']['gateway_access_token']
                    var_name = token_var[2:-1] # Strip ${...}
                    env_vars.append(f'{var_name}="pls_change_me_{secrets.token_hex(4)}"')
                    count += 1
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr); sys.exit(1)
        
        if count > 0:
            self._save_config(config)
            self._update_env_file(env_vars)
            print(f"\nSuccessfully created {count} new instance(s).")
        else:
            print("\nNo new instances were created.")

    def remove_instances(self, provider_args: List[str]):
        """Public method to remove provider instances."""
        config = self._load_config()
        if 'providers' not in config or not config['providers']:
            print("Error: No providers found in configuration to remove.", file=sys.stderr)
            sys.exit(1)
            
        all_names_to_remove = []
        try:
            for arg in provider_args:
                # We use the parser for consistent syntax, but ignore the provider_type.
                _provider_type, instance_names = self._parse_provider_arg(arg)
                all_names_to_remove.extend(instance_names)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr); sys.exit(1)
            
        not_found = [name for name in all_names_to_remove if name not in config['providers']]
        if not_found:
            print(f"Error: Instance(s) not found: {', '.join(not_found)}", file=sys.stderr)
            sys.exit(1)

        print("You are about to remove:", ", ".join(all_names_to_remove))
        response = input("Are you sure? [y/N]: ").lower().strip()
        if response == 'y':
            removed_count = sum(1 for name in all_names_to_remove if config['providers'].pop(name, None))
            self._save_config(config)
            print(f"\nSuccessfully removed {removed_count} instance(s).")
        else:
            print("Removal cancelled.")

    def list_instances(self):
        """Public method to list all configured provider instances."""
        if not os.path.exists(self.config_path):
            print(f"Config file not found: '{self.config_path}'.")
            return

        config = self._load_config()
        providers = config.get('providers')
        if not providers:
            print("No provider instances found.")
            return
        
        print(f"Configured provider instances ({len(providers)}):")
        max_len = max(len(name) for name in providers.keys()) if providers else 0
        for name, details in sorted(providers.items()):
            ptype = details.get('provider_type', 'N/A')
            status = "enabled" if details.get('enabled', False) else "disabled"
            print(f"  - {name:<{max_len}}  (type: {ptype}, status: {status})")

