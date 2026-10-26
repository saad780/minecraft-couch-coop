#!/usr/bin/python3
import sys
from mc_couch.prism import wrapper_main

if __name__ == "__main__":
    try:
        raise SystemExit(wrapper_main(sys.argv[1:]))
    except Exception as error:
        print("Minecraft Couch Co-op:", str(error), file=sys.stderr)
        raise SystemExit(1)
