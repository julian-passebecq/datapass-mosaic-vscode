"""Line-delimited JSON kernel RPC. One process owns one workspace catalog."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from .execution import Engine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory',required=True)
    parser.add_argument('--mode',default='auto')
    parser.add_argument('--trusted-python',action='store_true')
    args = parser.parse_args()
    engine = None
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if engine is None:
                engine = Engine(Path(args.directory), args.mode, args.trusted_python)
            payload = {'ok':True, 'result':engine.handle(request)}
        except Exception as error:
            # Subclasses (a SQL dialect's refusal) are rejected requests too, not an outage.
            payload = {'ok':False,'error':str(error),'error_type':'ValueError' if isinstance(error, ValueError) else type(error).__name__}
        encoded = json.dumps(payload, allow_nan=False, default=str)
        if len(encoded) > 3_000_000:
            encoded = json.dumps({'ok':False,'error':'Kernel output exceeded the 3 MB protocol limit.'})
        sys.stdout.write(encoded+'\n')
        sys.stdout.flush()
    if engine is not None:
        engine.catalog.close()


if __name__ == '__main__':
    main()
