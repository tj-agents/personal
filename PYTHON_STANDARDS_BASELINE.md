# Python standards baseline

Existing violations at `591ddef906faf0cabc9459308ec5fc6148a30279` are baselined by exact authored file and rule. New files receive all enabled checks. Remove an exception when repairing its source. The tool configuration owns enforcement; this document records the rollout evidence and rationale.

## Ruff

Reason: preserve existing implementations during the standards rollout. Each row records the existing count and a representative required repair. No wildcard path or whole-rule ignores were added.

| File | Rule | Existing count | Required repair |
| --- | --- | ---: | --- |
| `.agents/tests/test_personal_packaging.py` | `PT009` | 12 | Use a regular `assert` instead of unittest-style `assertEqual` |
| `.agents/tests/test_personal_packaging.py` | `TID251` | 1 | `unittest.TestCase` is banned: Use plain pytest functions and bare assertions. |
| `.agents/tests/test_personal_use.py` | `PLR6301` | 2 | Method `plugins` could be a function, class method, or static method |
| `.agents/tests/test_personal_use.py` | `PT009` | 3 | Use a regular `assert` instead of unittest-style `assertFalse` |
| `.agents/tests/test_personal_use.py` | `TID251` | 2 | `importlib.util.spec_from_file_location` is banned: Import the installed public API; do not load another checkout by path. |

## Expanded authored-source scope

The previous source allowlist skipped authored implementations and tests. Broad directory scopes now cover future sibling files. The following additional findings are unchanged from the recorded base commit and use exact file/module and diagnostic exceptions.

| File | Ruff rule | Existing count | Required repair |
| --- | --- | ---: | --- |
| `.agents/personal/policy/rules/scripts/personal_scope.py` | `E501` | 4 | Line too long (97 > 88) |
| `.agents/personal/policy/rules/scripts/personal_scope.py` | `I001` | 1 | Import block is un-sorted or un-formatted |
| `.agents/personal/utility/use/scripts/use.py` | `E501` | 21 | Line too long (109 > 88) |
| `.agents/personal/utility/use/scripts/use.py` | `I001` | 1 | Import block is un-sorted or un-formatted |
| `.agents/personal/utility/use/scripts/use.py` | `RET504` | 1 | Unnecessary assignment to `targets` before `return` statement |
| `.agents/personal/utility/use/scripts/use.py` | `TID251` | 1 | `sys.path` is banned: Install the declared dependency; do not modify the import search path. |
| `.agents/tests/test_use.py` | `E501` | 14 | Line too long (96 > 88) |
| `.agents/tests/test_use.py` | `I001` | 1 | Import block is un-sorted or un-formatted |
| `.agents/tests/test_use.py` | `PT009` | 50 | Use a regular `assert` instead of unittest-style `assertEqual` |
| `.agents/tests/test_use.py` | `TID251` | 2 | `importlib.util.spec_from_file_location` is banned: Import the installed public API; do not load another checkout by path. |

Additional exact legacy formatter paths:

- `.agents/personal/policy/rules/scripts/personal_scope.py`
- `.agents/personal/utility/use/scripts/use.py`
- `.agents/tests/test_use.py`

| File | Mypy module | Rule | Existing count | Required repair |
| --- | --- | --- | ---: | --- |
| `.agents/personal/policy/rules/scripts/personal_scope.py` | `personal_scope` | `no-untyped-def` | 3 | Function is missing a type annotation |
| `.agents/personal/utility/use/scripts/use.py` | `use` | `no-untyped-call` | 1 | Call to untyped function "policy" in typed context |
| `.agents/tests/test_personal_use.py` | `test_personal_use` | `arg-type` | 1 | Argument 1 to "module_from_spec" has incompatible type "ModuleSpec \| None"; expected "ModuleSpec" |
| `.agents/tests/test_personal_use.py` | `test_personal_use` | `no-any-return` | 1 | Returning Any from function declared to return "Path" |
| `.agents/tests/test_personal_use.py` | `test_personal_use` | `no-untyped-def` | 3 | Function is missing a return type annotation |
| `.agents/tests/test_personal_use.py` | `test_personal_use` | `union-attr` | 2 | Item "None" of "ModuleSpec \| None" has no attribute "loader" |
| `.agents/tests/test_use.py` | `test_use` | `arg-type` | 1 | Argument 1 to "module_from_spec" has incompatible type "ModuleSpec \| None"; expected "ModuleSpec" |
| `.agents/tests/test_use.py` | `test_use` | `no-untyped-call` | 5 | Call to untyped function "git" in typed context |
| `.agents/tests/test_use.py` | `test_use` | `no-untyped-def` | 22 | Function is missing a return type annotation |
| `.agents/tests/test_use.py` | `test_use` | `union-attr` | 2 | Item "None" of "ModuleSpec \| None" has no attribute "loader" |
