try:
    from typing import Union

    # Union[int, "T2"] is valid (ForwardRef)
    T1 = Union[int, "T2"]
    print("Union works with string forward ref.")
except Exception as e:
    print(f"Union failed: {e}")

try:
    # int | "T1" fails at runtime
    T2 = int | "T1"
    print("Pipe operator works with string forward ref.")
except TypeError:
    print("Pipe operator failed with TypeError (expected).")
except Exception as e:
    print(f"Pipe operator failed with: {e}")

try:
    # Python 3.12+ style
    # type ConfigDict = ... (PEP 695)
    # This requires 3.12+ parser support
    # We'll see if the environment supports it
    exec("""
type MyConfigValue = str | int | float | bool | None | MyConfigDict | list[MyConfigValue]
type MyConfigDict = dict[str, MyConfigValue]
print("PEP 695 type aliases work.")
""")
except SyntaxError:
    print("PEP 695 SyntaxError.")
except Exception as e:
    print(f"PEP 695 failed: {e}")
