from typing import Union

try:
    # This represents the issue user mentioned
    # Union works with strings
    T1 = Union[int, "T2"]
    print("Union with string works")
except Exception as e:
    print(f"Union failed: {e}")

try:
    # This represents the UP007 fix that fails
    # | does NOT work with strings at runtime
    T2 = int | "T1"
    print("Pipe with string works")
except TypeError as e:
    print(f"Pipe with string failed: {e}")
except Exception as e:
    print(f"Pipe with string failed with other error: {e}")

# Python 3.12+ syntax check (I am in 3.13 env?)
# We can't easily test PEP 695 syntax via 'exec' if the parser doesn't support it,
# but we can try writing a file and running it.
