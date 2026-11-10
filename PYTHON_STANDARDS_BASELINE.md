# Python standards baseline

Existing violations at `7e0b2a962df9ba1b90284990360cdbd9c49cbe3d` are baselined by exact authored file and rule. New files receive all enabled checks. Remove an exception when repairing its source. The tool configuration owns enforcement; this document records the rollout evidence and rationale.

## Ruff

Reason: preserve existing implementations during the standards rollout. Each row records the existing count and a representative required repair. No wildcard path or whole-rule ignores were added.

| File | Rule | Existing count | Required repair |
| --- | --- | ---: | --- |
| `.agents/tests/test_personal_packaging.py` | `PT009` | 12 | Use a regular `assert` instead of unittest-style `assertEqual` |
| `.agents/tests/test_personal_packaging.py` | `TID251` | 1 | `unittest.TestCase` is banned: Use plain pytest functions and bare assertions. |
| `.agents/tests/test_personal_shims.py` | `TID251` | 1 | `importlib.util.spec_from_file_location` is banned: Import the installed public API; do not load another checkout by path. |
| `.agents/tests/test_personal_use.py` | `PLR6301` | 2 | Method `plugins` could be a function, class method, or static method |
| `.agents/tests/test_personal_use.py` | `PT009` | 3 | Use a regular `assert` instead of unittest-style `assertFalse` |
| `.agents/tests/test_personal_use.py` | `TID251` | 2 | `importlib.util.spec_from_file_location` is banned: Import the installed public API; do not load another checkout by path. |

## Custom checker

Reason: preserve exact pre-existing custom-checker findings during the standards rollout. Each entry maps to one authored path and rule; repair the stated design issue and remove its exception. No generated or vendored path is included.

| File | Rule | Existing count | Required repair |
| --- | --- | ---: | --- |
| .agents/personal/utility/approve/scripts/approve.py | PY016 | 3 | Inject process state or confine the read to an entry-point main. |
| .agents/personal/utility/bot-identity/scripts/bot_identity.py | PY001 | 2 | Rewrite the nested comprehension as named loops or one generator. |
| .agents/personal/utility/bot-identity/scripts/bot_identity.py | PY016 | 11 | Inject process state or confine the read to an entry-point main. |
| .agents/tests/test_approve.py | PY016 | 9 | Inject process state or confine the read to an entry-point main. |
| .agents/tests/test_bot_identity.py | PY016 | 14 | Inject process state or confine the read to an entry-point main. |

## Expanded authored-source scope

The previous source allowlist skipped authored implementations and tests. Broad directory scopes now cover future sibling files. The following additional findings are unchanged from the recorded base commit and use exact file/module and diagnostic exceptions.

| File | Ruff rule | Existing count | Required repair |
| --- | --- | ---: | --- |
| `.agents/personal/policy/rules/scripts/personal_scope.py` | `E501` | 4 | Line too long (97 > 88) |
| `.agents/personal/policy/rules/scripts/personal_scope.py` | `I001` | 1 | Import block is un-sorted or un-formatted |
| `.agents/personal/utility/approve/scripts/approve.py` | `E501` | 20 | Line too long (113 > 88) |
| `.agents/personal/utility/approve/scripts/approve.py` | `TID251` | 1 | `sys.path` is banned: Install the declared dependency; do not modify the import search path. |
| `.agents/personal/utility/bot-identity/scripts/bot_identity.py` | `A002` | 1 | Function argument `format` is shadowing a Python builtin |
| `.agents/personal/utility/bot-identity/scripts/bot_identity.py` | `E501` | 131 | Line too long (104 > 88) |
| `.agents/personal/utility/bot-identity/scripts/bot_identity.py` | `I001` | 1 | Import block is un-sorted or un-formatted |
| `.agents/personal/utility/bot-identity/scripts/bot_identity.py` | `N801` | 1 | Class name `SID_AND_ATTRIBUTES` should use CapWords convention |
| `.agents/personal/utility/bot-identity/scripts/bot_identity.py` | `PLR6301` | 1 | Method `log_message` could be a function, class method, or static method |
| `.agents/personal/utility/bot-identity/scripts/bot_identity.py` | `PTH100` | 1 | `os.path.abspath()` should be replaced by `Path.resolve()` |
| `.agents/personal/utility/bot-identity/scripts/bot_identity.py` | `PTH105` | 3 | `os.replace()` should be replaced by `Path.replace()` |
| `.agents/personal/utility/bot-identity/scripts/bot_identity.py` | `RET507` | 1 | Unnecessary `elif` after `continue` statement |
| `.agents/personal/utility/bot-identity/scripts/bot_identity.py` | `TRY300` | 1 | Consider moving this statement to an `else` block |
| `.agents/personal/utility/bot-identity/scripts/bot_identity.py` | `UP012` | 1 | Unnecessary UTF-8 `encoding` argument to `encode` |
| `.agents/personal/utility/use/scripts/use.py` | `E501` | 21 | Line too long (109 > 88) |
| `.agents/personal/utility/use/scripts/use.py` | `I001` | 1 | Import block is un-sorted or un-formatted |
| `.agents/personal/utility/use/scripts/use.py` | `RET504` | 1 | Unnecessary assignment to `targets` before `return` statement |
| `.agents/personal/utility/use/scripts/use.py` | `TID251` | 1 | `sys.path` is banned: Install the declared dependency; do not modify the import search path. |
| `.agents/tests/test_approve.py` | `E501` | 53 | Line too long (102 > 88) |
| `.agents/tests/test_approve.py` | `PLR6301` | 1 | Method `store` could be a function, class method, or static method |
| `.agents/tests/test_approve.py` | `PT009` | 36 | Use a regular `assert` instead of unittest-style `assertEqual` |
| `.agents/tests/test_approve.py` | `PTH123` | 1 | `open()` should be replaced by `Path.open()` |
| `.agents/tests/test_approve.py` | `TID251` | 4 | `importlib.util.spec_from_file_location` is banned: Import the installed public API; do not load another checkout by path. |
| `.agents/tests/test_bot_identity.py` | `B905` | 1 | `zip()` without an explicit `strict=` parameter |
| `.agents/tests/test_bot_identity.py` | `E501` | 128 | Line too long (108 > 88) |
| `.agents/tests/test_bot_identity.py` | `I001` | 1 | Import block is un-sorted or un-formatted |
| `.agents/tests/test_bot_identity.py` | `PLR6301` | 4 | Method `token` could be a function, class method, or static method |
| `.agents/tests/test_bot_identity.py` | `PT009` | 103 | Use a regular `assert` instead of unittest-style `assertEqual` |
| `.agents/tests/test_bot_identity.py` | `SIM117` | 4 | Use a single `with` statement with multiple contexts instead of nested `with` statements |
| `.agents/tests/test_bot_identity.py` | `TID251` | 4 | `importlib.util.spec_from_file_location` is banned: Import the installed public API; do not load another checkout by path. |
| `.agents/tests/test_use.py` | `E501` | 14 | Line too long (96 > 88) |
| `.agents/tests/test_use.py` | `I001` | 1 | Import block is un-sorted or un-formatted |
| `.agents/tests/test_use.py` | `PT009` | 50 | Use a regular `assert` instead of unittest-style `assertEqual` |
| `.agents/tests/test_use.py` | `TID251` | 2 | `importlib.util.spec_from_file_location` is banned: Import the installed public API; do not load another checkout by path. |

Additional exact legacy formatter paths:

- `.agents/personal/policy/rules/scripts/personal_scope.py`
- `.agents/personal/utility/approve/scripts/approve.py`
- `.agents/personal/utility/bot-identity/scripts/bot_identity.py`
- `.agents/personal/utility/use/scripts/use.py`
- `.agents/tests/test_approve.py`
- `.agents/tests/test_bot_identity.py`
- `.agents/tests/test_use.py`

| File | Mypy module | Rule | Existing count | Required repair |
| --- | --- | --- | ---: | --- |
| `.agents/personal/policy/rules/scripts/personal_scope.py` | `personal_scope` | `no-untyped-def` | 3 | Function is missing a type annotation |
| `.agents/personal/utility/approve/scripts/approve.py` | `approve` | `arg-type` | 2 | Argument 1 to "bot_authored" has incompatible type "object"; expected "dict[Any, Any]" |
| `.agents/personal/utility/approve/scripts/approve.py` | `approve` | `attr-defined` | 2 | "object" has no attribute "get" |
| `.agents/personal/utility/approve/scripts/approve.py` | `approve` | `index` | 3 | Value of type "dict[Any, Any] \| None" is not indexable |
| `.agents/personal/utility/approve/scripts/approve.py` | `approve` | `no-any-return` | 2 | Returning Any from function declared to return "CompletedProcess[Any]" |
| `.agents/personal/utility/approve/scripts/approve.py` | `approve` | `no-untyped-def` | 8 | Function is missing a type annotation for one or more parameters |
| `.agents/personal/utility/approve/scripts/approve.py` | `approve` | `type-arg` | 7 | Missing type arguments for generic type "CompletedProcess" |
| `.agents/personal/utility/bot-identity/scripts/bot_identity.py` | `bot_identity` | `arg-type` | 1 | Argument 1 to "get" of "dict" has incompatible type "tuple[str, ...]"; expected "tuple[str, str]" |
| `.agents/personal/utility/bot-identity/scripts/bot_identity.py` | `bot_identity` | `attr-defined` | 8 | "BaseServer" has no attribute "server_port" |
| `.agents/personal/utility/bot-identity/scripts/bot_identity.py` | `bot_identity` | `no-any-return` | 8 | Returning Any from function declared to return "dict[Any, Any]" |
| `.agents/personal/utility/bot-identity/scripts/bot_identity.py` | `bot_identity` | `no-untyped-def` | 13 | Function is missing a type annotation for one or more parameters |
| `.agents/personal/utility/bot-identity/scripts/bot_identity.py` | `bot_identity` | `type-arg` | 15 | Missing type arguments for generic type "dict" |
| `.agents/personal/utility/bot-identity/scripts/bot_identity.py` | `bot_identity` | `union-attr` | 2 | Item "None" of "str \| None" has no attribute "split" |
| `.agents/personal/utility/use/scripts/use.py` | `use` | `no-untyped-call` | 1 | Call to untyped function "policy" in typed context |
| `.agents/tests/test_approve.py` | `test_approve` | `arg-type` | 1 | Argument 1 to "module_from_spec" has incompatible type "ModuleSpec \| None"; expected "ModuleSpec" |
| `.agents/tests/test_approve.py` | `test_approve` | `assignment` | 1 | Incompatible types in assignment (expression has type "_patch_dict", variable has type "_patch_pass_arg[MagicMock \| AsyncMock]") |
| `.agents/tests/test_approve.py` | `test_approve` | `no-untyped-call` | 71 | Call to untyped function "ref" in typed context |
| `.agents/tests/test_approve.py` | `test_approve` | `no-untyped-def` | 27 | Function is missing a type annotation |
| `.agents/tests/test_approve.py` | `test_approve` | `union-attr` | 2 | Item "None" of "ModuleSpec \| None" has no attribute "loader" |
| `.agents/tests/test_approve.py` | `test_approve` | `var-annotated` | 1 | Need type annotation for "cases" |
| `.agents/tests/test_bot_identity.py` | `test_bot_identity` | `arg-type` | 3 | Argument 1 to "module_from_spec" has incompatible type "ModuleSpec \| None"; expected "ModuleSpec" |
| `.agents/tests/test_bot_identity.py` | `test_bot_identity` | `attr-defined` | 13 | "GhWrapperTests" has no attribute "real_gh" |
| `.agents/tests/test_bot_identity.py` | `test_bot_identity` | `no-untyped-call` | 67 | Call to untyped function "FakeGitHub" in typed context |
| `.agents/tests/test_bot_identity.py` | `test_bot_identity` | `no-untyped-def` | 94 | Function is missing a type annotation |
| `.agents/tests/test_bot_identity.py` | `test_bot_identity` | `union-attr` | 2 | Item "None" of "ModuleSpec \| None" has no attribute "loader" |
| `.agents/tests/test_personal_use.py` | `test_personal_use` | `arg-type` | 1 | Argument 1 to "module_from_spec" has incompatible type "ModuleSpec \| None"; expected "ModuleSpec" |
| `.agents/tests/test_personal_use.py` | `test_personal_use` | `no-any-return` | 1 | Returning Any from function declared to return "Path" |
| `.agents/tests/test_personal_use.py` | `test_personal_use` | `no-untyped-def` | 3 | Function is missing a return type annotation |
| `.agents/tests/test_personal_use.py` | `test_personal_use` | `union-attr` | 2 | Item "None" of "ModuleSpec \| None" has no attribute "loader" |
| `.agents/tests/test_use.py` | `test_use` | `arg-type` | 1 | Argument 1 to "module_from_spec" has incompatible type "ModuleSpec \| None"; expected "ModuleSpec" |
| `.agents/tests/test_use.py` | `test_use` | `no-untyped-call` | 5 | Call to untyped function "git" in typed context |
| `.agents/tests/test_use.py` | `test_use` | `no-untyped-def` | 22 | Function is missing a return type annotation |
| `.agents/tests/test_use.py` | `test_use` | `union-attr` | 2 | Item "None" of "ModuleSpec \| None" has no attribute "loader" |
