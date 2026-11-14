import argparse

from cassette_fm import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cassette-dj")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    parser.print_help()
    return 0
