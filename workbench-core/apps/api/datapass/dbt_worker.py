"""One isolated invocation using the API's own Python/dbt installation."""
from __future__ import annotations
import sys
from pathlib import Path

def main() -> int:
    # Running this file by path inserts datapass/ in sys.path. dbt discovers all
    # top-level dbt_* modules there, including our adapter files. They are not
    # plugins; remove only that directory before importing dbt.
    own_directory = Path(__file__).resolve().parent
    sys.path[:] = [p for p in sys.path if Path(p).resolve() != own_directory]
    args = sys.argv[1:]
    if not args or args[0] not in {'parse', 'compile', 'seed', 'run', 'build', 'test'}:
        print('Unsupported Datapass dbt action.', file=sys.stderr)
        return 2
    # The stable entrypoint accepts CLI-style arguments. Do not reuse its mutable
    # objects or invoke dbt concurrently inside the control-plane process.
    from dbt.cli.main import dbtRunner
    result = dbtRunner().invoke(args)
    if result.exception:
        print(str(result.exception), file=sys.stderr)
        return 2
    return 0 if result.success else 1

if __name__ == '__main__':
    raise SystemExit(main())
