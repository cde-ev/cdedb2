#!/usr/bin/env python3

import argparse
import pathlib
import shutil
import subprocess
import tempfile
import zipapp


REPOPATH = pathlib.Path(__file__).parent.parent


def work(args):
    with tempfile.TemporaryDirectory() as tmp:
        pkg = pathlib.Path(tmp) / 'verify_result'
        pkg.mkdir()
        shutil.copy2(REPOPATH / 'related' / 'verify_result.py',
                     pkg / '__main__.py')
        subprocess.run(['python3', '-m', 'pip', 'install',
                        'schulze_condorcet==2.0.0', '--target', 'verify_result'],
                       cwd=tmp, check=True)
        shutil.rmtree(pkg / 'schulze_condorcet-2.0.0.dist-info')
        zipapp.create_archive(pkg, args.output,
                              interpreter='/usr/bin/env python3')


def main():
    parser = argparse.ArgumentParser(
        description=(
            'Create zipapp for verifying vote result files.'
            ' This is necessary to bundle the schulze-condorcet code.'))
    parser.add_argument('output', help="Path to output file")
    args = parser.parse_args()
    work(args)


if __name__ == "__main__":
    main()
