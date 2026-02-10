try:
    type ConfigValue = str | int | float | bool | None | ConfigDict | list[ConfigValue]
    type ConfigDict = dict[str, ConfigValue]
    print("PEP 695 type aliases work correctly.")
except SyntaxError:
    print("PEP 695 syntax not supported (SyntaxError).")
except NameError:
    # If recursive definitions cause runtime issues (unlikely with 'type')
    print("NameError with PEP 695.")
except Exception as e:
    print(f"PEP 695 failed: {e}")
