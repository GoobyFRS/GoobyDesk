# AI Instructions

You are assisting with GoobyDesk_Modern. An Open-Source, Cloud Native, Lightweight, Databaseless, Self-Hosted ITSM Service Desk.

**Entry Point:** `app.py`

**Setup:**

```shell
source venv/bin/activate
pip install -r requirements.txt
python3 flask run --debug
```

Always prefer:

- simplicity
- maintainability
- security
- readability
- never use single character variables

Never introduce unnecessary frameworks. Never add dependencies unless requested. When unsure, ask instead of inventing behavior.

Avoid global states.

Favor composition over inheritance.

Document public APIs.

Write production-quality code.

Use async only when it materially improves concurrency, responsiveness, or I/O scalability. Avoid unnecessary async complexity.

## Language Preference

- **Primary language**: Python 3
- **Secondary language**: vanilla JavaScript
- **Compliance**: PEP8 compliant

### Imports

 Order imports in groups, separated by blank lines.

1. Standard library
2. Third-party packages
3. Local/project imports

### Naming Conventions

| Type | Convention | Example |
| --- | --- | --- |
| Variables | `snake_case` | `user_count`, `total_items` |
| Constants | `UPPERCASE` | `MAX_RETRIES`, `API_BASE_URL` |
| Functions | `snake_case` | `get_user_data()`, `calculate_total()` |
| Classes | `PascalCase` | `UsercodeManager`, `DataProcessor` |
| Private/Internal | `_leading_underscore` | `_internal_helper()`, `_cache` |
| Ignored variables | `_` prefix | `for _ in range(10)`, `x, _ = get_pair()` |
| Module constants | `SCREAMING_SNAKE_CASE` | `DEFAULT_TIMEOUT = 30` |

### Security Requirements

- Never hardcode secrets
- Use environment variables for configuration
- Validate all user input
- Escape or sanitize rendered content
- Prefer parameterized database queries
- Avoid shell=True in subprocess calls
- Use least-privilege principles
- Authentication and authorization checks must be explicit
- Log security-relevant events

### Logging

- Use structured logging where practical
- Never log secrets or credentials
- Include contextual identifiers in logs
- Prefer informative warnings/errors over generic messages

### Function Guidelines

- Keep functions under ~50 lines when practical
- Use descriptive names that indicate purpose
- Prefer pure functions where possible

### Type Hints

Type Hints should be used as often as reasonably possible but also remain human readable.

### Nesting

- **Maximum nesting depth**: 4 levels
- Use early returns, guard clauses, and extraction to reduce nesting
- Prefer flat over nested

```python
# Bad - too nested
def process(data):
    if data:
        if data.is_valid:
            if data.has_items:
                for item in data.items:
                    if item.active:
                        # deeply nested logic

# Good - use early returns
def process(data):
    if not data or not data.is_valid:
        return None
    if not data.has_items:
        return []
    return [item for item in data.items if item.active]
```

### Docstrings

- Use **Google style** docstrings
- Required for public functions, classes, and modules
- Include: summary, args, returns, raises (when applicable)

## Safety-Critical Code Principles (Power of 10 - Python Adaptation)

These principles are adapted from NASA/JPL's "Power of 10" rules for safety-critical C code. They ensure code is analyzable, predictable, and verifiable.

### 1. Simple Control Flow

- **No recursion** in production code (direct or indirect)
- Avoid complex control flow that's hard to trace
- Use iteration instead of recursion; if recursion is unavoidable, add explicit depth limits

```python
# Bad - unbounded recursion
def traverse(node):
    if node is None:
        return
    process(node)
    traverse(node.left)
    traverse(node.right)

# Good - iterative with explicit stack
def traverse(node):
    stack = [node]
    while stack:
        current = stack.pop()
        if current is None:
            continue
        process(current)
        stack.append(current.right)
        stack.append(current.left)

# Acceptable - recursion with depth limit for non-critical code
MAX_RECURSION_DEPTH = 100

def traverse(node, depth: int = 0):
    if depth > MAX_RECURSION_DEPTH:
        raise RecursionError("Maximum traversal depth exceeded")
    if node is None:
        return
    process(node)
    traverse(node.left, depth + 1)
    traverse(node.right, depth + 1)
```

### 2. Fixed Loop Bounds

- All loops must have a **deterministic, verifiable upper bound** unless the loop is part of a long-running service worker
with explicit cancellation or timeout handling.
- Avoid `while True` without clear, guaranteed exit conditions
- Use `for` loops with explicit ranges when possible

```python
# Bad - unbounded loop
while True:
    data = fetch_next()
    if not data:
        break
    process(data)

# Good - explicit bounds
MAX_ITERATIONS = 512

for _ in range(MAX_ITERATIONS):
    data = fetch_next()
    if not data:
        break
    process(data)
else:
    raise RuntimeError("Loop did not terminate within expected iterations")
```

### 3. Bounded Data Structures

- **Pre-allocate** collections where size is known
- Set **explicit size limits** on dynamic collections
- Avoid unbounded growth in queues, caches, and buffers

```python
from collections import deque

# Bad - unbounded growth
cache = {}
def add_to_cache(key, value):
    cache[key] = value  # Can grow forever

# Good - bounded with maxlen
cache = deque(maxlen=1000)

# Good - explicit limit with LRU
from functools import lru_cache

@lru_cache(maxsize=1000)
def expensive_computation(x: int) -> int:
    return x ** 2
```

### 4. Short Functions

- **Maximum 60 lines** per function (fits on one screen/page)
- Single responsibility - if you can't describe it in one sentence, split it
- Extract helpers for complex logic

### 6. Minimal Variable Scope

- Declare variables **as close to first use** as possible
- Avoid module-level mutable state
- Use local variables over instance variables when possible
- Delete references to large objects when no longer needed

```python
# Bad - variable declared far from use
def process_data(items):
    result = []  # Declared here...

    # ... 50 lines of other code ...

    for item in items:  # ... used here
        result.append(transform(item))
    return result

# Good - variable declared at point of use
def process_data(items):
    # ... other code ...

    result = [transform(item) for item in items]
    return result
```

### 7. Check All Return Values

- **Never ignore return values** from functions that can fail
- Handle `None` explicitly - don't let it propagate silently
- Use type hints to make return types explicit

```python
# Bad - ignoring potential None
def get_user_name(user_id: int) -> str:
    user = database.get_user(user_id)  # Could return None
    return user.name  # AttributeError if None

# Good - explicit handling
def get_user_name(user_id: int) -> str | None:
    user = database.get_user(user_id)
    if user is None:
        logger.warning(f"User not found: {user_id}")
        return None
    return user.name

# Better - fail fast with clear error
def get_user_name(user_id: int) -> str:
    user = database.get_user(user_id)
    if user is None:
        raise ValueError(f"User not found: {user_id}")
    return user.name
```

### 8. Limit Metaprogramming

- **No `exec()` or `eval()`** - ever
- Limit decorator nesting to **2 levels maximum**
- Avoid `__getattr__` magic unless absolutely necessary
- No dynamic class generation in production code

```python
# Bad - dynamic code execution
def run_user_code(code_string: str):
    exec(code_string)  # Security nightmare, unanalyzable

# Bad - excessive decorator stacking
@decorator_a
@decorator_b
@decorator_c
@decorator_d  # Too many layers
def my_function():
    pass

# Good - limited, clear decorators
@lru_cache(maxsize=100)
@log_execution_time
def my_function():
    pass
```

### 9. Limit Data Structure Nesting

- Maximum **3 levels** of nested data structures
- Avoid deeply nested dicts/lists - use dataclasses or named tuples
- If you need `data["a"]["b"]["c"]["d"]`, refactor

```python
# Bad - deeply nested
config = {
    "server": {
        "database": {
            "connection": {
                "pool": {
                    "size": 10  # data["server"]["database"]["connection"]["pool"]["size"]
                }
            }
        }
    }
}

# Good - flat with dataclasses
from dataclasses import dataclass

@dataclass
class PoolConfig:
    size: int = 10

@dataclass
class DatabaseConfig:
    pool: PoolConfig

@dataclass
class ServerConfig:
    database: DatabaseConfig

config = ServerConfig(database=DatabaseConfig(pool=PoolConfig(size=10)))
print(config.database.pool.size)  # Clear, type-checked access
```
