"""Manual offline worker only; never starts recording from app startup."""
import argparse
from pathlib import Path
from radioflix.timefree.store import TimefreeStore
from radioflix.timefree.worker import FixturePHP, TimefreeWorker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture', action='store_true', required=True)
    parser.add_argument('--db', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--source', required=True)
    args = parser.parse_args()
    # Keep this milestone's CLI physically confined to test data.
    for value in (args.db, args.output):
        if not Path(value).resolve().is_relative_to('/tmp'):
            parser.error('offline worker paths must be under /tmp')
    worker = TimefreeWorker(TimefreeStore(args.db), args.output, FixturePHP(['php'], args.source))
    worker.run_once()


if __name__ == '__main__':
    main()
