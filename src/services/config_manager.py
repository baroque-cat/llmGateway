# src/services/config_manager.py

import os
import re
import sys
import copy
from typing import List, Tuple, Dict, Any

from ruamel.yaml import YAML

# Assuming these files are in the src/config directory
from src.config.defaults import get_default_config
from src.config.provider_templates import PROVIDER_TYPE_DEFAULTS

class ConfigManager:
    """
    A service class to manage the providers.yaml configuration file programmatically.
    It handles creation, deletion, listing, and validation of provider instances.
    """
    def __init__(
        self,
        config_path: str = "config/providers.yaml",
        env_path: str = ".env",
        keys_base_path: str = "keys",
        proxies_base_path: str = "proxies",
    ):
        """
        Initializes the ConfigManager.

        Args:
            config_path: Path to the main YAML configuration file.
            env_path: Path to the environment variables file.
            keys_base_path: Base path for storing API key files.
            proxies_base_path: Base path for storing proxy list files.
        """
        self.config_path = config_path
        self.env_path = env_path
        self.keys_base_path = keys_base_path
        self.proxies_base_path = proxies_base_path
        
        # Initialize ruamel.yaml to preserve comments and formatting
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.indent(mapping=2, sequence=4, offset=2)
        
        # Regex to validate provider instance names (letters, numbers, underscore, hyphen)
        # Must not start or end with a hyphen or underscore.
        self.name_validation_pattern = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9_-]*[a-zA-Z0-9])?$")

    def _load_config(self) -> Dict[str, Any]:
        """
        Loads the existing YAML config or creates a base structure if it doesn't exist.
        """
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return self.yaml.load(f)
        else:
            print(f"Configuration file not found at '{self.config_path}'. A new one will be created.")
            # Use the global structure from defaults, but with an empty providers dict
            default_conf = get_default_config()
            default_conf['providers'] = {} # Start with an empty provider list
            return default_conf

    def _save_config(self, config_data: Dict[str, Any]):
        """
        Saves the configuration data back to the YAML file.
        """
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                self.yaml.dump(config_data, f)
        except PermissionError:
            print(f"Error: Permission denied to write to '{self.config_path}'. Please check file permissions.", file=sys.stderr)
            sys.exit(1)

    def _validate_instance_name(self, name: str):
        """
        Validates that the instance name is suitable for use in file paths and variable names.
        """
        if not self.name_validation_pattern.match(name):
            print(
                f"Error: Invalid instance name '{name}'. Names must contain only letters, numbers, underscores, or hyphens, "
                "and cannot start or end with a hyphen or underscore.",
                file=sys.stderr
            )
            sys.exit(1)

    def _parse_provider_arg(self, provider_arg: str) -> Tuple[str, List[str]]:
        """
        Parses a command-line argument like 'gemini:name1,name2'.
        """
        if ':' not in provider_arg or provider_arg.count(':') > 1:
            raise ValueError(f"Invalid format for provider argument '{provider_arg}'. Expected format: 'type:name1,name2'")
        
        provider_type, names_str = provider_arg.split(':', 1)
        
        if not provider_type:
            raise ValueError("Provider type cannot be empty.")
        if not names_str:
            raise ValueError("At least one instance name must be provided.")
        
        provider_names = [name.strip() for name in names_str.split(',')]
        
        if not all(provider_names):
            raise ValueError("Instance names cannot be empty (e.g., 'type:name1,,name2').")
        
        return provider_type, provider_names

    def _build_new_instance(self, provider_type: str, instance_name: str) -> Dict[str, Any]:
        """
        Constructs the configuration dictionary for a new provider instance.
        """
        base_template = get_default_config()['providers']['llm_provider_default']
        new_instance = copy.deepcopy(base_template)

        if provider_type not in PROVIDER_TYPE_DEFAULTS:
            supported_types = ", ".join(PROVIDER_TYPE_DEFAULTS.keys())
            print(f"Error: Unsupported provider type '{provider_type}'. Supported types are: {supported_types}", file=sys.stderr)
            sys.exit(1)
        
        type_specifics = PROVIDER_TYPE_DEFAULTS[provider_type]
        new_instance.update(type_specifics)

        new_instance['provider_type'] = provider_type
        new_instance['keys_path'] = os.path.join(self.keys_base_path, instance_name, '')
        new_instance['proxy_config']['pool_list_path'] = os.path.join(self.proxies_base_path, instance_name, '')

        token_var_name = f"{instance_name.upper().replace('-', '_')}_TOKEN"
        new_instance['access_control']['gateway_access_token'] = f"${{{token_var_name}}}"
        
        return new_instance

    def _create_related_directories(self, instance_name: str):
        """
        Creates the 'keys' and 'proxies' directories for the new instance.
        """
        dirs_to_create = [
            os.path.join(self.keys_base_path, instance_name),
            os.path.join(self.proxies_base_path, instance_name)
        ]
        for dir_path in dirs_to_create:
            try:
                os.makedirs(dir_path, exist_ok=True)
                print(f"Ensured directory exists: '{dir_path}'")
            except PermissionError:
                print(f"Warning: Permission denied to create directory '{dir_path}'. Please create it manually.", file=sys.stderr)
            except Exception as e:
                print(f"Warning: Could not create directory '{dir_path}': {e}", file=sys.stderr)

    def _update_env_file(self, vars_to_add: List[str]):
        """
        Creates or updates the .env file with new variable placeholders.
        """
        if not vars_to_add:
            return

        existing_vars = set()
        if os.path.exists(self.env_path):
            with open(self.env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    match = re.match(r'^\s*([a-zA-Z0-9_]+)=', line)
                    if match:
                        existing_vars.add(match.group(1))

        vars_to_actually_add = []
        for var_assignment in vars_to_add:
            var_name = var_assignment.split('=', 1)[0]
            if var_name not in existing_vars:
                vars_to_actually_add.append(var_assignment)
        
        if vars_to_actually_add:
            try:
                with open(self.env_path, 'a', encoding='utf-8') as f:
                    if os.path.getsize(self.env_path) > 0:
                        f.write("\n")
                    f.write("# Added by llmGateway config manager\n")
                    for var_line in vars_to_actually_add:
                        f.write(f"{var_line}\n")
                print(f"Updated '{self.env_path}' with {len(vars_to_actually_add)} new variable placeholder(s). Please set their values.")
            except PermissionError:
                print(f"Warning: Permission denied to write to '{self.env_path}'. Please add the following lines manually:", file=sys.stderr)
                for var_line in vars_to_actually_add:
                    print(f"  {var_line}", file=sys.stderr)

    def create_instances(self, provider_args: List[str]):
        """
        Public method to create one or more provider instances.
        """
        config = self._load_config()
        env_vars_to_add = []
        instances_created_count = 0

        for arg in provider_args:
            try:
                provider_type, instance_names = self._parse_provider_arg(arg)
                for name in instance_names:
                    self._validate_instance_name(name)
                    if 'providers' in config and name in config['providers']:
                        print(f"Warning: Provider instance '{name}' already exists. Skipping.")
                        continue
                    
                    print(f"Creating instance '{name}' of type '{provider_type}'...")
                    new_instance_config = self._build_new_instance(provider_type, name)
                    if 'providers' not in config:
                        config['providers'] = {}
                    config['providers'][name] = new_instance_config
                    
                    self._create_related_directories(name)
                    
                    token_var = new_instance_config['access_control']['gateway_access_token']
                    var_name = token_var[2:-1]
                    env_vars_to_add.append(f'{var_name}=""')
                    
                    instances_created_count += 1

            except ValueError as e:
                print(f"Error processing argument '{arg}': {e}", file=sys.stderr)
                sys.exit(1)
        
        if instances_created_count > 0:
            self._save_config(config)
            self._update_env_file(env_vars_to_add)
            print(f"\nSuccessfully created {instances_created_count} new provider instance(s) in '{self.config_path}'.")
        else:
            print("\nNo new instances were created.")

    def _confirm_removal(self, names_to_remove: List[str]) -> bool:
        """
        Asks the user for confirmation before deleting.
        """
        print("You are about to remove the following provider instance(s) from your configuration:")
        for name in names_to_remove:
            print(f"  - {name}")
        print("This action will NOT delete key files, directories, or .env variables.")
        
        try:
            response = input("Are you sure you want to continue? [y/N]: ").lower().strip()
            return response == 'y'
        except (KeyboardInterrupt, EOFError):
            print("\nRemoval cancelled.")
            return False

    def remove_instances(self, names_to_remove: List[str]):
        """
        Public method to remove one or more provider instances.
        """
        config = self._load_config()
        
        clean_names_to_remove = [name.strip() for name in names_to_remove]
        
        if 'providers' not in config:
            print(f"Error: The configuration file has no 'providers' section.", file=sys.stderr)
            sys.exit(1)

        not_found = [name for name in clean_names_to_remove if name not in config['providers']]
        if not_found:
            print(f"Error: The following instance(s) were not found in the configuration: {', '.join(not_found)}", file=sys.stderr)
            sys.exit(1)
        
        if self._confirm_removal(clean_names_to_remove):
            instances_removed_count = 0
            for name in clean_names_to_remove:
                if name in config['providers']:
                    del config['providers'][name]
                    instances_removed_count += 1
            
            self._save_config(config)
            print(f"\nSuccessfully removed {instances_removed_count} instance(s) from '{self.config_path}'.")
        else:
            print("Removal operation cancelled by user.")

    def list_instances(self):
        """
        Public method to list all configured provider instances.
        """
        if not os.path.exists(self.config_path):
            print(f"Configuration file '{self.config_path}' not found. Nothing to list.")
            print(f"You can create a new configuration using: python main.py config create <type>:<name>")
            return

        config = self._load_config()
        providers = config.get('providers')

        if not providers:
            print(f"No provider instances found in '{self.config_path}'.")
            return
        
        print(f"Found {len(providers)} provider instance(s) in '{self.config_path}':")
        # Find the longest name for formatting
        max_len = max(len(name) for name in providers.keys()) if providers else 0
        
        for name, details in sorted(providers.items()):
            ptype = details.get('provider_type', 'N/A')
            enabled = "enabled" if details.get('enabled', False) else "disabled"
            print(f"  - {name:<{max_len}} (type: {ptype}, status: {enabled})")

